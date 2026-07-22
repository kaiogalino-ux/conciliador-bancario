"""Pré-requisito da camada de IA (ver docs/HISTORICO_DECISOES.md): antes de
qualquer alteração para a IA identificar o índice exato de origem de cada
linha do Resultado, foi preciso confirmar que `linha.name` (onde `linha` é
sempre um `df_erp.loc[i]`/`df_banco.loc[j]`) já preserva esse índice em
`_linha_resultado_erp`/`_linha_resultado_banco` — sem precisar de nenhum
parâmetro novo nem alterar nenhum dos call sites existentes.

Este teste prova essa garantia diretamente, chamando as duas funções com
linhas sintéticas obtidas via `.loc[i]`/`.loc[j]`, com e sem `par_id`.
"""

from datetime import date

from src.conciliador import _linha_resultado_banco, _linha_resultado_erp
from tests.conftest import construir_df_banco, construir_df_erp


def test_linha_resultado_erp_preserva_erp_index_via_name():
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 1), "valor": 100.00, "favorecido": "Fornecedor A"},
        {"data_usada": date(2026, 5, 2), "valor": 200.00, "favorecido": "Fornecedor B"},
        {"data_usada": date(2026, 5, 3), "valor": 300.00, "favorecido": "Fornecedor C"},
    ])

    for i in df_erp.index:
        linha = _linha_resultado_erp(
            df_erp.loc[i], "Revisão Manual", "obs", "Revisão Manual", None, None, None, None,
        )
        assert linha["_erp_index"] == i
        assert linha["_banco_index"] is None


def test_linha_resultado_erp_preserva_banco_index_via_par_id():
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 1), "valor": 100.00, "favorecido": "Fornecedor A"},
    ])

    linha = _linha_resultado_erp(
        df_erp.loc[0], "Conciliado", "", "Valor e data", date(2026, 5, 1), -100.00, "PAGTO A", 0,
        par_id=(0, 7),
    )
    assert linha["_erp_index"] == 0
    assert linha["_banco_index"] == 7


def test_linha_resultado_banco_preserva_banco_index_via_name():
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 1), "valor": -100.00, "favorecido": "PAGTO A"},
        {"data": date(2026, 5, 2), "valor": -200.00, "favorecido": "PAGTO B"},
    ])

    for j in df_banco.index:
        linha = _linha_resultado_banco(
            df_banco.loc[j], "Somente banco", "", "Somente banco", None, "", None, None, None,
        )
        assert linha["_banco_index"] == j
        assert linha["_erp_index"] is None


def test_linha_resultado_banco_preserva_erp_index_via_par_id():
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 1), "valor": -100.00, "favorecido": "PAGTO A"},
    ])

    linha = _linha_resultado_banco(
        df_banco.loc[0], "Conciliado", "", "Valor e data", date(2026, 5, 1), "Data de confirmação", 100.00,
        "Fornecedor A", 0, par_id=(5, 0),
    )
    assert linha["_banco_index"] == 0
    assert linha["_erp_index"] == 5


def test_indices_internos_nunca_aparecem_no_resultado_final(logger_silencioso):
    """Confirma, num cenário real de `conciliar()`, que as chaves internas
    `_erp_index`/`_banco_index`/`_par_id` nunca vazam para o DataFrame final —
    `COLUNAS_RESULTADO` continua sendo a única fonte de colunas."""
    from src.conciliador import COLUNAS_RESULTADO, conciliar

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 1), "valor": 100.00, "favorecido": "Fornecedor A"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 1), "valor": -100.00, "favorecido": "PAGTO FORNECEDOR A"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert list(resultado.columns) == COLUNAS_RESULTADO
    assert "_erp_index" not in resultado.columns
    assert "_banco_index" not in resultado.columns
    assert "_par_id" not in resultado.columns
