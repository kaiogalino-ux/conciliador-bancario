"""Preparação dos arquivos de cada execução pedida pela interface web.

O pipeline oficial (`src/leitor_erp.py` e `src/leitor_banco.py`) lê o arquivo
mais recente de uma *pasta*, não um arquivo avulso. Este módulo é a ponte:
recebe os uploads, grava cada um na pasta certa de uma execução isolada e
devolve os três caminhos que `executar_conciliacao_web` espera.

Nenhuma regra de conciliação vive aqui.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

EXTENSOES_ERP = (".xlsx", ".xls")
EXTENSOES_BANCO = (".ofx", ".xlsx", ".xls")
LIMITE_ARQUIVO_BYTES = 30 * 1024 * 1024

NOME_RESULTADO = "Resultado.xlsx"
HORAS_RETENCAO_PADRAO = 6

VARIAVEL_PASTA_EXECUCOES = "CONCILIADOR_RUNTIME_DIR"
PASTA_EXECUCOES_PADRAO = Path(__file__).resolve().parent.parent / ".web-runtime"

_CARACTERES_INVALIDOS = re.compile(r"[^\w.-]+")
_HIFENS_NAS_PONTAS = re.compile(r"^-+|-+$")


class ErroDeValidacao(ValueError):
    """Arquivo enviado não atende às regras de formato/tamanho.

    Sinaliza erro do usuário (HTTP 400), nunca falha do servidor.
    """


@dataclass(frozen=True)
class Execucao:
    """Os caminhos de uma única execução da conciliação."""

    run_id: str
    pasta_erp: Path
    pasta_banco: Path
    caminho_resultado: Path


def pasta_execucoes() -> Path:
    """Raiz onde as execuções são gravadas.

    Em produção aponta para um diretório temporário do host (via
    `CONCILIADOR_RUNTIME_DIR`), porque o código pode estar num disco
    somente-leitura.
    """
    configurada = os.environ.get(VARIAVEL_PASTA_EXECUCOES, "").strip()
    return Path(configurada) if configurada else PASTA_EXECUCOES_PADRAO


def nome_seguro(nome_original: str, alternativa: str) -> str:
    """Sanitiza o nome do arquivo enviado, preservando a extensão.

    A extensão importa: os leitores decidem entre OFX e Excel por ela.
    """
    caminho = Path(nome_original.replace("\\", "/"))
    extensao = caminho.suffix.lower()
    # NFKD separa "ó" em "o" + acento; descartar o acento evita que ele vire
    # um hífen no meio da palavra ("Relato-rio"), comum em nomes brasileiros.
    decomposto = unicodedata.normalize("NFKD", caminho.stem)
    base = "".join(letra for letra in decomposto if not unicodedata.combining(letra))
    base = _CARACTERES_INVALIDOS.sub("-", base)
    base = _HIFENS_NAS_PONTAS.sub("", base)[:80]
    return f"{base or alternativa}{extensao}"


def validar_upload(
    nome_arquivo: str | None,
    tamanho: int,
    rotulo: str,
    extensoes: tuple[str, ...],
) -> None:
    """Aplica as mesmas regras de formato e tamanho das outras interfaces."""
    if not nome_arquivo or tamanho <= 0:
        raise ErroDeValidacao(f"Selecione o arquivo {rotulo}.")

    extensao = Path(nome_arquivo.replace("\\", "/")).suffix.lower()
    if extensao not in extensoes:
        aceitas = ", ".join(extensoes)
        raise ErroDeValidacao(f"{rotulo}: formato não aceito. Use {aceitas}.")

    if tamanho > LIMITE_ARQUIVO_BYTES:
        raise ErroDeValidacao(f"{rotulo}: o arquivo deve ter no máximo 30 MB.")


def criar_execucao() -> Execucao:
    """Cria as pastas isoladas de uma nova execução."""
    run_id = str(uuid4())
    raiz = pasta_execucoes() / run_id
    pasta_erp = raiz / "erp"
    pasta_banco = raiz / "banco"

    pasta_erp.mkdir(parents=True, exist_ok=True)
    pasta_banco.mkdir(parents=True, exist_ok=True)

    return Execucao(
        run_id=run_id,
        pasta_erp=pasta_erp,
        pasta_banco=pasta_banco,
        caminho_resultado=raiz / NOME_RESULTADO,
    )


def gravar_upload(destino: Path, nome_original: str, alternativa: str, conteudo: bytes) -> Path:
    """Grava um upload dentro da pasta da execução e devolve o caminho final."""
    caminho = destino / nome_seguro(nome_original, alternativa)
    caminho.write_bytes(conteudo)
    return caminho


def caminho_resultado(run_id: str) -> Path | None:
    """Localiza o Resultado.xlsx de uma execução já concluída.

    Devolve `None` quando o `run_id` não é um UUID válido — assim um caminho
    forjado nunca escapa da pasta de execuções.
    """
    try:
        UUID(run_id)
    except (ValueError, AttributeError, TypeError):
        return None

    caminho = pasta_execucoes() / run_id / NOME_RESULTADO
    return caminho if caminho.is_file() else None


def limpar_execucoes_antigas(horas: int = HORAS_RETENCAO_PADRAO) -> int:
    """Remove execuções antigas e devolve quantas foram apagadas.

    O servidor é um processo longo (diferente do uso local, que termina a cada
    execução), então sem esta limpeza os uploads e planilhas se acumulariam
    indefinidamente no disco temporário.
    """
    raiz = pasta_execucoes()
    if not raiz.is_dir():
        return 0

    limite = time.time() - horas * 3600
    removidas = 0

    for pasta in raiz.iterdir():
        if not pasta.is_dir():
            continue
        try:
            if pasta.stat().st_mtime >= limite:
                continue
            shutil.rmtree(pasta, ignore_errors=True)
            removidas += 1
        except OSError:
            # Uma execução que não pôde ser apagada (arquivo em uso, por
            # exemplo) nunca deve interromper a conciliação em andamento.
            continue

    return removidas
