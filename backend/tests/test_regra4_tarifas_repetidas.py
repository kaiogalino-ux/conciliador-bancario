"""Regra 4 (CLAUDE.md): tarifas repetidas — se o ERP e o banco tiverem mesma
data, mesmo valor, mesma descrição e mesma quantidade, conciliar individualmente
uma a uma. Nunca resumir em uma linha de grupo: cada tarifa deve continuar
aparecendo como sua própria linha conciliada no Resultado.xlsx.
"""

from datetime import date

from src.conciliador import STATUS_CONCILIADO, TIPO_DUPLICIDADE_IDENTICA, conciliar
from tests.conftest import construir_df_banco, construir_df_erp


def test_tarifas_repetidas_conciliam_uma_a_uma(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 8), "valor": 9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data_usada": date(2026, 5, 8), "valor": 9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data_usada": date(2026, 5, 8), "valor": 9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 8), "valor": -9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data": date(2026, 5, 8), "valor": -9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data": date(2026, 5, 8), "valor": -9.80, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    # 3 pares distintos (1 tarifa ERP x 1 tarifa banco cada) — Regra 1
    # (2026-07-10-b): cada par vira uma única linha, nunca duas espelhadas
    # nem uma única linha resumindo o grupo inteiro.
    assert len(resultado) == 3
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_DUPLICIDADE_IDENTICA).all()
    assert (resultado["Origem"] == "ERP+Banco").all()


def test_quantidade_diferente_nao_concilia_como_identica(logger_silencioso):
    """Se a quantidade não bater (2 tarifas no ERP x 3 no banco), não pode
    conciliar como duplicidade idêntica — fica em Revisão Manual."""
    from src.conciliador import STATUS_REVISAO_MANUAL

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 8), "valor": 4.35, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data_usada": date(2026, 5, 8), "valor": 4.35, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 8), "valor": -4.35, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data": date(2026, 5, 8), "valor": -4.35, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
        {"data": date(2026, 5, 8), "valor": -4.35, "favorecido": "TARIFA BANCARIA TRANSF PGTO PIX"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
