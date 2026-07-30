"""Testes da camada Streamlit sem duplicar as regras de conciliação."""

from io import BytesIO
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


RAIZ_PROJETO = Path(__file__).resolve().parent.parent
APP_STREAMLIT = RAIZ_PROJETO / "streamlit_app.py"
MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _excel_bytes(linhas: list[dict]) -> bytes:
    memoria = BytesIO()
    pd.DataFrame(linhas).to_excel(memoria, index=False)
    return memoria.getvalue()


def _botao_por_chave(app: AppTest, chave: str):
    return next(botao for botao in app.button if botao.key == chave)


def test_streamlit_inicia_com_uploads_e_acao_bloqueada():
    app = AppTest.from_file(str(APP_STREAMLIT)).run(timeout=30)

    assert not app.exception
    assert len(app.get("file_uploader")) == 2
    assert _botao_por_chave(app, "executar_conciliacao").disabled is True


def test_streamlit_executa_pipeline_e_disponibiliza_excel(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("IA_MODO", "DESATIVADA")

    erp = _excel_bytes(
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
    banco = _excel_bytes(
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

    app = AppTest.from_file(str(APP_STREAMLIT)).run(timeout=30)
    app.get("file_uploader")[0].set_value(
        ("erp_teste.xlsx", erp, MIME_EXCEL)
    )
    app.get("file_uploader")[1].set_value(
        ("banco_teste.xlsx", banco, MIME_EXCEL)
    )
    app.run(timeout=30)

    botao = _botao_por_chave(app, "executar_conciliacao")
    assert botao.disabled is False
    botao.click().run(timeout=90)

    assert not app.exception
    resultado = app.session_state.resultado_conciliacao
    assert resultado["indicadores"]["conciliado"]["quantidade"] == 1
    assert resultado["indicadores"]["somenteBanco"]["quantidade"] == 1
    assert app.session_state.resultado_excel.startswith(b"PK")
    assert any(
        botao.key == "download_resultado"
        for botao in app.get("download_button")
    )
