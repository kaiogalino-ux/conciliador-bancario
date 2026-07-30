"""Servidor HTTP do Conciliador Bancário.

Expõe o pipeline oficial de `src/` como API para o frontend Next.js hospedado
na Vercel. O contrato JSON devolvido é exatamente o mesmo que a interface já
consumia quando o Python rodava na mesma máquina — o que mudou foi só o
transporte.

Rodar localmente:

    cd backend
    uvicorn api.main:app --reload
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

RAIZ_BACKEND = Path(__file__).resolve().parent.parent
if str(RAIZ_BACKEND) not in sys.path:
    sys.path.insert(0, str(RAIZ_BACKEND))

from fastapi import Depends, FastAPI, File, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.armazenamento import (
    EXTENSOES_BANCO,
    EXTENSOES_ERP,
    ErroDeValidacao,
    caminho_resultado,
    criar_execucao,
    finalizar_execucao,
    gravar_upload,
    limpar_execucoes_antigas,
    validar_upload,
)
from src.web_runner import executar_conciliacao_web

logger = logging.getLogger("conciliador_api")

VARIAVEL_ORIGENS = "CORS_ORIGINS"
VARIAVEL_TOKEN = "API_TOKEN"

ORIGENS_PADRAO_LOCAIS = ("http://localhost:3000", "http://127.0.0.1:3000")

NOME_DOWNLOAD = "Resultado_conciliacao.xlsx"
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def origens_permitidas() -> list[str]:
    """Origens autorizadas a chamar a API, vindas de `CORS_ORIGINS`.

    Sem a variável definida, só o frontend rodando na própria máquina é
    aceito. Nunca liberamos `*`: a API recebe planilhas financeiras.
    """
    configuradas = os.environ.get(VARIAVEL_ORIGENS, "")
    origens = [origem.strip() for origem in configuradas.split(",") if origem.strip()]
    return origens or list(ORIGENS_PADRAO_LOCAIS)


def _erro(mensagem: str, status: int, detalhe: str | None = None) -> JSONResponse:
    """Formato de erro que o frontend já sabe interpretar."""
    corpo: dict[str, str] = {"error": mensagem}
    if detalhe:
        corpo["detail"] = detalhe
    return JSONResponse(corpo, status_code=status)


async def exigir_token(x_api_token: str | None = Header(default=None)) -> None:
    """Confere o token compartilhado, quando `API_TOKEN` está configurada.

    Sem a variável definida a API fica aberta — é o modo de uso local. Este
    token barra acesso casual à URL pública; não identifica o usuário (ver
    docs/HISTORICO_DECISOES.md).
    """
    esperado = os.environ.get(VARIAVEL_TOKEN, "").strip()
    if not esperado:
        return
    if not x_api_token or not secrets.compare_digest(x_api_token, esperado):
        raise PermissaoNegada()


class PermissaoNegada(Exception):
    """Token ausente ou inválido."""


app = FastAPI(
    title="Conciliador Bancário — API",
    description="Interface HTTP do pipeline de conciliação (regras em src/).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origens_permitidas(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-API-Token", "Content-Type"],
)


@app.exception_handler(PermissaoNegada)
async def _tratar_permissao(request: Request, exc: PermissaoNegada) -> JSONResponse:
    return _erro("Acesso não autorizado.", 401)


@app.get("/health")
async def health() -> dict:
    """Verificação de saúde usada pelo host (Render)."""
    return {"status": "ok"}


@app.post("/api/reconcile", dependencies=[Depends(exigir_token)])
async def reconciliar(
    erp: UploadFile = File(...),
    bank: UploadFile = File(...),
) -> JSONResponse:
    """Executa a conciliação sobre os dois arquivos enviados."""
    execucao = None
    try:
        conteudo_erp = await erp.read()
        conteudo_banco = await bank.read()

        validar_upload(erp.filename, len(conteudo_erp), "da Gestão", EXTENSOES_ERP)
        validar_upload(bank.filename, len(conteudo_banco), "do banco", EXTENSOES_BANCO)

        limpar_execucoes_antigas()
        execucao = criar_execucao()

        gravar_upload(execucao.pasta_erp, erp.filename, "gestao", conteudo_erp)
        gravar_upload(execucao.pasta_banco, bank.filename, "banco", conteudo_banco)

        # A conciliação é bloqueante e usa CPU (pandas + busca de combinações
        # do lote NET EMP), então roda fora do event loop.
        resultado = await run_in_threadpool(
            executar_conciliacao_web,
            execucao.pasta_erp,
            execucao.pasta_banco,
            execucao.caminho_resultado,
        )

        resultado["runId"] = execucao.run_id
        resultado["downloadUrl"] = f"/api/reconcile/{execucao.run_id}/download"
        resultado["files"] = {"erp": erp.filename, "bank": bank.filename}
        return JSONResponse(resultado)

    except ErroDeValidacao as erro:
        return _erro(str(erro), 400)
    except Exception as erro:  # noqa: BLE001 — a causa real vai em "detail".
        logger.exception("Falha ao executar a conciliação solicitada pela interface.")
        return _erro(
            "A conciliação não foi concluída. Verifique os arquivos e tente novamente.",
            500,
            str(erro)[:600],
        )
    finally:
        # Vale para sucesso e para erro: o ERP e o extrato saem do disco assim
        # que a conciliação termina. Só o Resultado.xlsx fica, até o download.
        if execucao is not None:
            finalizar_execucao(execucao)


@app.get("/api/reconcile/{run_id}/download", dependencies=[Depends(exigir_token)])
async def baixar_resultado(run_id: str):
    """Devolve o Resultado.xlsx gerado por uma execução."""
    caminho = caminho_resultado(run_id)
    if caminho is None:
        return _erro("O arquivo desta execução não está mais disponível.", 404)

    return FileResponse(
        caminho,
        media_type=TIPO_XLSX,
        filename=NOME_DOWNLOAD,
        headers={"Cache-Control": "private, no-store"},
    )
