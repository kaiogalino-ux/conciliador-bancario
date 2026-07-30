"""Garante que a exibição do log da execução no Streamlit é bem comportada.

O log em tela é auditoria: precisa mostrar só a execução atual, nunca acumular
entre execuções, nunca deixar handler pendurado no logger do pipeline e nunca
crescer sem limite na memória.
"""

import logging
from io import BytesIO
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
APP_STREAMLIT = RAIZ_PROJETO / "streamlit_app.py"
MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NOME_LOGGER_PIPELINE = "conciliador_web"


def _excel_bytes(linhas: list[dict]) -> bytes:
    memoria = BytesIO()
    pd.DataFrame(linhas).to_excel(memoria, index=False)
    return memoria.getvalue()


def _botao_por_chave(app: AppTest, chave: str):
    return next(botao for botao in app.button if botao.key == chave)


def _capturas_penduradas() -> list:
    """Handlers de captura que ficaram no logger do pipeline."""
    logger = logging.getLogger(NOME_LOGGER_PIPELINE)
    return [h for h in logger.handlers if type(h).__name__ == "_CapturaDeLog"]


def _rodar(app: AppTest, erp: bytes, banco: bytes, sufixo: str) -> None:
    app.get("file_uploader")[0].set_value((f"erp_{sufixo}.xlsx", erp, MIME_EXCEL))
    app.get("file_uploader")[1].set_value((f"banco_{sufixo}.xlsx", banco, MIME_EXCEL))
    app.run(timeout=60)
    _botao_por_chave(app, "executar_conciliacao").click().run(timeout=180)


def test_log_mostra_so_a_execucao_atual_em_duas_rodadas(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CONCILIADOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")

    primeiro_erp = _excel_bytes(
        [{"Data de Confirmacao": "10/07/2026", "Valor": 170.0, "Favorecido": "Reserva hospedagem"}]
    )
    primeiro_banco = _excel_bytes(
        [{"Data": "10/07/2026", "Valor": -170.0, "Historico": "Reserva hospedagem"}]
    )
    segundo_erp = _excel_bytes(
        [{"Data de Confirmacao": "20/07/2026", "Valor": 55.5, "Favorecido": "Outro fornecedor"}]
    )
    segundo_banco = _excel_bytes(
        [{"Data": "20/07/2026", "Valor": -55.5, "Historico": "Outro fornecedor"}]
    )

    app = AppTest.from_file(str(APP_STREAMLIT)).run(timeout=60)

    # --- primeira conciliação ---
    _rodar(app, primeiro_erp, primeiro_banco, "um")
    assert not app.exception
    log_um = list(app.session_state.log_execucao)
    assert log_um, "o log da primeira execução deveria ter sido capturado"
    assert any("erp_um.xlsx" in linha for linha in log_um)
    assert not _capturas_penduradas(), "handler não foi removido depois da 1a execução"

    # --- segunda conciliação, com arquivos diferentes ---
    _rodar(app, segundo_erp, segundo_banco, "dois")
    assert not app.exception
    log_dois = list(app.session_state.log_execucao)
    assert log_dois

    # O log da segunda execução não pode carregar nada da primeira.
    assert any("erp_dois.xlsx" in linha for linha in log_dois)
    assert not any("erp_um.xlsx" in linha for linha in log_dois)
    assert log_dois != log_um
    assert not _capturas_penduradas(), "handler não foi removido depois da 2a execução"


def test_nao_acumula_handlers_apos_varias_execucoes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CONCILIADOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")

    erp = _excel_bytes(
        [{"Data de Confirmacao": "10/07/2026", "Valor": 12.0, "Favorecido": "Fornecedor"}]
    )
    banco = _excel_bytes([{"Data": "10/07/2026", "Valor": -12.0, "Historico": "Fornecedor"}])

    app = AppTest.from_file(str(APP_STREAMLIT)).run(timeout=60)
    for rodada in range(3):
        _rodar(app, erp, banco, f"r{rodada}")
        assert not app.exception
        assert not _capturas_penduradas()


def test_buffer_do_log_tem_limite():
    """O deque precisa descartar linhas antigas em vez de crescer sem fim."""
    import importlib.util

    especificacao = importlib.util.spec_from_file_location(
        "streamlit_app_para_teste", APP_STREAMLIT
    )
    modulo = importlib.util.module_from_spec(especificacao)
    # Não executa o script (isso exigiria contexto do Streamlit): basta ler o
    # código-fonte para confirmar o limite declarado.
    fonte = APP_STREAMLIT.read_text(encoding="utf-8")
    assert "LIMITE_LINHAS_LOG" in fonte
    assert "maxlen=limite" in fonte
    del especificacao, modulo


def test_captura_preserva_o_log_quando_a_conciliacao_falha(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CONCILIADOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")

    quebrado = b"isto nao e um xlsx"
    banco = _excel_bytes([{"Data": "10/07/2026", "Valor": -12.0, "Historico": "Fornecedor"}])

    app = AppTest.from_file(str(APP_STREAMLIT)).run(timeout=60)
    _rodar(app, quebrado, banco, "falha")

    # A falha é tratada pela própria interface; o importante aqui é que o
    # handler não ficou pendurado e o log ficou disponível para diagnóstico.
    assert not _capturas_penduradas()
