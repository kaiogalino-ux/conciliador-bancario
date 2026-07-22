"""Regra 3 (CLAUDE.md): conciliação individual.

- mesmo valor e mesma data (par único) deve conciliar;
- se houver duplicidade de valor e data, tentar desempatar por descrição/nome;
- se não houver segurança nenhuma, manter Revisão Manual (nunca adivinhar).
"""

from datetime import date

from src.conciliador import (
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    TIPO_VALOR_DATA_NOME,
    TIPO_VALOR_E_DATA,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp


def test_par_unico_mesmo_valor_e_data_concilia(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 10), "valor": 353.00, "favorecido": "IB Extintores - NF 2037"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 10), "valor": -353.00, "favorecido": "PIX ENVIADO DES: IB EXTINTORES"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    # Par 1-para-1: a Regra 1 (2026-07-10-b) mescla numa única linha.
    assert len(resultado) == 1
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_E_DATA).all()
    assert resultado.iloc[0]["Origem"] == "ERP+Banco"


def test_duplicidade_com_nomes_diferentes_desempata_por_descricao(logger_silencioso):
    """Dois lançamentos com mesmo valor e mesma data no ERP e no banco, mas com
    nomes próprios diferentes que aparecem nos dois lados — deve conciliar cada
    um com o par certo, nunca ao acaso."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 12), "valor": 672.08, "favorecido": "REEMBOLSO AUXÍLIO CRECHE - Alfredo Neto"},
        {"data_usada": date(2026, 5, 12), "valor": 672.08, "favorecido": "REEMBOLSO AUXÍLIO CRECHE - Érica mattos"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 12), "valor": -672.08, "favorecido": "PIX ENVIADO DES: ALFREDO PEDRO DA SILV 12/05"},
        {"data": date(2026, 5, 12), "valor": -672.08, "favorecido": "PIX ENVIADO DES: Erica Mattos Ramos    12/05"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_DATA_NOME).all()

    alfredo_erp = resultado[resultado["Descrição ERP"].str.contains("Alfredo", na=False)]
    assert alfredo_erp["Descrição Banco"].str.contains("ALFREDO", case=False).all()

    erica_erp = resultado[resultado["Descrição ERP"].str.contains("mattos", case=False, na=False)]
    assert erica_erp["Descrição Banco"].str.contains("Erica", case=False).all()


def test_duplicidade_sem_descricao_suficiente_mantem_revisao_manual(logger_silencioso):
    """Mesmo valor e mesma data nos dois lados, mas as descrições não têm nenhum
    termo em comum entre ERP e banco — não há como saber qual é qual, então
    nunca deve adivinhar: todos ficam em Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 20), "valor": 250.00, "favorecido": "Serviço Diversos A"},
        {"data_usada": date(2026, 5, 20), "valor": 250.00, "favorecido": "Serviço Diversos A"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 20), "valor": -250.00, "favorecido": "PAGTO ELETRON COBRANCA XPTO"},
        {"data": date(2026, 5, 20), "valor": -250.00, "favorecido": "PAGTO ELETRON COBRANCA XPTO"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].notna().all()
