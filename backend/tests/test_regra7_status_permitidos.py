"""Regra 7 (CLAUDE.md): os status permitidos no Resultado.xlsx devem continuar
sendo somente estes quatro — nenhum outro valor pode aparecer na coluna
"Status", em nenhuma combinação de cenários.
"""

from datetime import date

from src.conciliador import (
    STATUS_CONCILIADO,
    STATUS_NAO_ENCONTRADO_BANCO,
    STATUS_REVISAO_MANUAL,
    STATUS_SOMENTE_BANCO,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp

STATUS_PERMITIDOS = {
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    STATUS_NAO_ENCONTRADO_BANCO,
    STATUS_SOMENTE_BANCO,
}


def test_apenas_os_quatro_status_permitidos_aparecem(logger_silencioso):
    df_erp = construir_df_erp([
        # Concilia normalmente.
        {"data_usada": date(2026, 5, 1), "valor": 100.00, "favorecido": "Fornecedor A"},
        # Duplicidade sem descrição suficiente -> Revisão Manual.
        {"data_usada": date(2026, 5, 2), "valor": 200.00, "favorecido": "Serviço Genérico"},
        {"data_usada": date(2026, 5, 2), "valor": 200.00, "favorecido": "Serviço Genérico"},
        # Sem par nenhum no banco -> Não encontrado no banco.
        {"data_usada": date(2026, 5, 3), "valor": 999.00, "favorecido": "Fornecedor Sem Par"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 1), "valor": -100.00, "favorecido": "PAGTO FORNECEDOR A"},
        {"data": date(2026, 5, 2), "valor": -200.00, "favorecido": "PAGTO ELETRON COBRANCA XPTO"},
        {"data": date(2026, 5, 2), "valor": -200.00, "favorecido": "PAGTO ELETRON COBRANCA XPTO"},
        # Sem par nenhum no ERP -> Somente banco.
        {"data": date(2026, 5, 4), "valor": -777.00, "favorecido": "PAGTO SEM PAR NO ERP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    status_encontrados = set(resultado["Status"].unique())
    assert status_encontrados <= STATUS_PERMITIDOS

    # Confere que o cenário realmente exercitou os quatro status.
    assert status_encontrados == STATUS_PERMITIDOS
