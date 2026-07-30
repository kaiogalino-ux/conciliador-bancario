"""Regra 5 (CLAUDE.md): PIX, TED e DOC com nome específico devem ser
conciliados individualmente por valor, data e descrição/nome — nunca devem
entrar na regra de lote, mesmo quando aparecem várias vezes na mesma data.
"""

from datetime import date

from src.conciliador import (
    STATUS_CONCILIADO,
    TIPO_CONCILIACAO_LOTE_CONSOLIDADO,
    TIPO_VALOR_DATA_NOME,
    _e_candidato_lote_banco,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp


def test_pix_ted_doc_nunca_sao_candidatos_a_lote():
    assert _e_candidato_lote_banco("PIX ENVIADO DES: FULANO DA SILVA 15/05") is False
    assert _e_candidato_lote_banco("TED DIF.TITUL.CC H.BANK DEST. FULANO LTDA") is False
    assert _e_candidato_lote_banco("DOC/TED INTERNET TED INTERNET") is False


def test_pix_individuais_ambiguos_sao_resolvidos_por_nome_nao_por_lote(logger_silencioso):
    """Dois PIX com o mesmo valor e mesma data (ambíguos por valor/data) devem
    ser desempatados pelo nome do favorecido — e não podem, de forma alguma,
    virar um "lote"."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 15), "valor": 300.00, "favorecido": "PROV-081/2026 Anderson Pirinê"},
        {"data_usada": date(2026, 5, 15), "valor": 300.00, "favorecido": "PROV-082/2026 Mauro Vagner"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 15), "valor": -300.00, "favorecido": "PIX ENVIADO DES: ANDERSON PIRINE DA CO 15/05"},
        {"data": date(2026, 5, 15), "valor": -300.00, "favorecido": "PIX ENVIADO DES: MAURO VAGNER DA COSTA 15/05"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_DATA_NOME).all()
    assert (resultado["Tipo Conciliação"] != TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()
    assert resultado["ID Lote"].isna().all()

    anderson = resultado[resultado["Descrição ERP"].str.contains("Anderson", na=False)]
    assert anderson["Descrição Banco"].str.contains("ANDERSON", case=False).all()
