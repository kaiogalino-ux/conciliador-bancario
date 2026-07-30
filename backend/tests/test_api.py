"""Testes da camada HTTP (`api/`) sem duplicar nenhuma regra de conciliação.

A API é só transporte: estes testes verificam formato de erro, validação de
upload, isolamento entre execuções e o contrato JSON que o frontend consome.
As regras em si continuam cobertas pelos testes de `src/`.
"""

from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.armazenamento import LIMITE_ARQUIVO_BYTES, nome_seguro

MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel_bytes(linhas: list[dict]) -> bytes:
    memoria = BytesIO()
    pd.DataFrame(linhas).to_excel(memoria, index=False)
    return memoria.getvalue()


def _erp_exemplo() -> bytes:
    return _excel_bytes(
        [
            {
                "Data de Confirmacao": "10/07/2026",
                "Valor": 170.0,
                "Favorecido": "Reserva hospedagem",
            },
            {
                "Data de Confirmacao": "11/07/2026",
                "Valor": 228.0,
                "Favorecido": "Flash",
            },
        ]
    )


def _banco_exemplo() -> bytes:
    return _excel_bytes(
        [
            {
                "Data": "10/07/2026",
                "Valor": -170.0,
                "Historico": "Reserva hospedagem",
            },
            {
                "Data": "12/07/2026",
                "Valor": -9.8,
                "Historico": "Tarifa bancaria",
            },
        ]
    )


@pytest.fixture
def cliente(tmp_path, monkeypatch) -> TestClient:
    """API isolada: cada teste grava suas execuções numa pasta própria."""
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "execucoes"))
    monkeypatch.setenv("CONCILIADOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")
    monkeypatch.delenv("API_TOKEN", raising=False)

    from api.main import app

    return TestClient(app)


def _enviar(cliente: TestClient, *, erp=None, banco=None, headers=None):
    arquivos = {
        "erp": erp or ("erp_teste.xlsx", _erp_exemplo(), MIME_EXCEL),
        "bank": banco or ("banco_teste.xlsx", _banco_exemplo(), MIME_EXCEL),
    }
    return cliente.post("/api/reconcile", files=arquivos, headers=headers or {})


def test_health_responde_ok(cliente):
    resposta = cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_conciliacao_devolve_o_contrato_esperado_pelo_frontend(cliente):
    resposta = _enviar(cliente)

    assert resposta.status_code == 200
    corpo = resposta.json()

    # Campos que o React lê diretamente (app/page.tsx).
    assert set(corpo) >= {
        "runId",
        "downloadUrl",
        "files",
        "periodo",
        "entradas",
        "indicadores",
        "pendentes",
        "pendentesTotal",
        "pendentesExibidos",
    }
    assert corpo["downloadUrl"] == f"/api/reconcile/{corpo['runId']}/download"
    assert corpo["files"] == {"erp": "erp_teste.xlsx", "bank": "banco_teste.xlsx"}

    indicadores = corpo["indicadores"]
    assert set(indicadores) >= {
        "totalGestao",
        "totalBanco",
        "conciliado",
        "revisaoManual",
        "somenteBanco",
        "naoEncontradoBanco",
        "totalLinhas",
    }
    # Mesmo cenário do teste da interface Streamlit: 1 par bate, a tarifa não.
    assert indicadores["conciliado"]["quantidade"] == 1
    assert indicadores["somenteBanco"]["quantidade"] == 1


def test_download_devolve_o_xlsx_da_execucao(cliente):
    corpo = _enviar(cliente).json()

    resposta = cliente.get(corpo["downloadUrl"])

    assert resposta.status_code == 200
    assert resposta.content.startswith(b"PK")
    assert "Resultado_conciliacao.xlsx" in resposta.headers["content-disposition"]


def test_execucoes_diferentes_nao_compartilham_resultado(cliente):
    primeira = _enviar(cliente).json()
    segunda = _enviar(cliente).json()

    assert primeira["runId"] != segunda["runId"]
    assert cliente.get(primeira["downloadUrl"]).status_code == 200
    assert cliente.get(segunda["downloadUrl"]).status_code == 200


def test_extensao_invalida_e_erro_do_usuario(cliente):
    resposta = _enviar(
        cliente, erp=("planilha.txt", b"conteudo qualquer", "text/plain")
    )

    assert resposta.status_code == 400
    assert "formato não aceito" in resposta.json()["error"]


def test_arquivo_acima_do_limite_e_recusado(cliente):
    gigante = b"x" * (LIMITE_ARQUIVO_BYTES + 1)

    resposta = _enviar(cliente, erp=("grande.xlsx", gigante, MIME_EXCEL))

    assert resposta.status_code == 400
    assert "30 MB" in resposta.json()["error"]


def test_arquivo_vazio_e_recusado(cliente):
    resposta = _enviar(cliente, erp=("vazio.xlsx", b"", MIME_EXCEL))

    assert resposta.status_code == 400
    assert "Selecione o arquivo" in resposta.json()["error"]


def test_falha_do_pipeline_vira_500_com_detalhe(cliente):
    # Extensão válida, conteúdo que não é um Excel: o leitor precisa falhar
    # como erro de servidor, com a causa em "detail".
    resposta = _enviar(cliente, erp=("quebrado.xlsx", b"isto nao e um xlsx", MIME_EXCEL))

    assert resposta.status_code == 500
    corpo = resposta.json()
    assert corpo["error"].startswith("A conciliação não foi concluída")
    assert corpo["detail"]


def test_download_de_execucao_inexistente_devolve_404(cliente):
    inexistente = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

    resposta = cliente.get(f"/api/reconcile/{inexistente}/download")

    assert resposta.status_code == 404


def test_run_id_forjado_nao_escapa_da_pasta_de_execucoes(cliente):
    resposta = cliente.get("/api/reconcile/nao-e-um-uuid/download")

    assert resposta.status_code == 404


def test_token_bloqueia_quando_configurado(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "execucoes"))
    monkeypatch.setenv("CONCILIADOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")
    monkeypatch.setenv("API_TOKEN", "segredo-de-teste")

    from api.main import app

    cliente = TestClient(app)

    assert _enviar(cliente).status_code == 401
    assert _enviar(cliente, headers={"X-API-Token": "errado"}).status_code == 401
    assert (
        _enviar(cliente, headers={"X-API-Token": "segredo-de-teste"}).status_code == 200
    )


@pytest.mark.parametrize(
    ("original", "esperado"),
    [
        ("Relatório de Contas.xlsx", "Relatorio-de-Contas.xlsx"),
        ("../../etc/passwd.xlsx", "passwd.xlsx"),
        ("C:\\temp\\extrato.OFX", "extrato.ofx"),
        ("!!!.xls", "gestao.xls"),
    ],
)
def test_nome_seguro_preserva_extensao_e_remove_caminho(original, esperado):
    assert nome_seguro(original, "gestao") == esperado


def test_limpeza_remove_execucoes_antigas(tmp_path, monkeypatch):
    import os
    import time

    from api.armazenamento import criar_execucao, limpar_execucoes_antigas

    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "execucoes"))

    antiga = criar_execucao()
    recente = criar_execucao()

    envelhecido = time.time() - 24 * 3600
    os.utime(antiga.pasta_erp.parent, (envelhecido, envelhecido))

    removidas = limpar_execucoes_antigas(horas=6)

    assert removidas == 1
    assert not antiga.pasta_erp.parent.exists()
    assert recente.pasta_erp.parent.exists()
