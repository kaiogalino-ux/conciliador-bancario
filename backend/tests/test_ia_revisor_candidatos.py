"""Testes unitários (sem passar por conciliar()) de src/ia_revisor.py:
seleção de candidatos bancários por regra objetiva e critério de
elegibilidade da IA. Ver docs/HISTORICO_DECISOES.md para as regras.
"""

from datetime import date

from src.conciliador import (
    MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA,
    MOTIVO_MULTIPLOS_CANDIDATOS,
    MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO,
    MOTIVO_NOME_INSUFICIENTE,
    MOTIVO_QUANTIDADE_DIVERGENTE,
    MOTIVO_REMUNERACAO_SEM_NOME,
    MOTIVO_SEM_DATA_PAGAMENTO,
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    _linha_resultado_erp,
)
from src.ia_config import ConfiguracaoIA
from src.ia_revisor import _elegivel_para_ia, _selecionar_candidatos_banco
from tests.conftest import construir_df_banco, construir_df_erp

CONFIG_PADRAO = ConfiguracaoIA(
    modo="SOMBRA",
    api_key="sk-teste",
    modelo="openai/gpt-oss-120b",
    janela_busca_dias=0,
    janela_automatica_dias=0,
    maximo_candidatos=5,
    confianca_minima_sombra=0.70,
    confianca_minima_automatico=0.95,
)


def _erp_unico(data_usada, valor, favorecido="Fornecedor Ambíguo", categoria=""):
    return construir_df_erp([
        {"data_usada": data_usada, "valor": valor, "favorecido": favorecido, "categoria": categoria},
    ])


# ---------------------------------------------------------------------------
# _selecionar_candidatos_banco
# ---------------------------------------------------------------------------


def test_candidato_da_mesma_data_entra():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "PIX QUALQUER"},
    ])

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, df_banco.index, CONFIG_PADRAO)

    assert candidatos == [0]


def test_candidato_de_data_diferente_fica_de_fora():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 15), "valor": -500.00, "favorecido": "PIX QUALQUER"},  # 5 dias
    ])

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, df_banco.index, CONFIG_PADRAO)

    assert candidatos == []


def test_candidato_alem_da_janela_fica_de_fora():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 16), "valor": -500.00, "favorecido": "PIX QUALQUER"},  # 6 dias
    ])

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, df_banco.index, CONFIG_PADRAO)

    assert candidatos == []


def test_valor_precisa_bater_exatamente():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -500.01, "favorecido": "PIX QUALQUER"},
    ])

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, df_banco.index, CONFIG_PADRAO)

    assert candidatos == []


def test_indice_fora_do_pool_disponivel_nunca_aparece():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "PIX QUALQUER"},
    ])

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, bancos_disponiveis=[], config_ia=CONFIG_PADRAO)

    assert candidatos == []


def test_corta_no_maximo_configurado_apenas_entre_candidatos_da_mesma_data():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "D"},
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "A"},  # 0 dias
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "B"},
        {"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "C"},
        {"data": date(2026, 6, 11), "valor": -500.00, "favorecido": "AB"},  # excluído
        {"data": date(2026, 6, 15), "valor": -500.00, "favorecido": "E"},  # 5 dias
    ])
    config = ConfiguracaoIA(
        modo="SOMBRA", api_key="sk", modelo="m", janela_busca_dias=5, janela_automatica_dias=1,
        maximo_candidatos=3, confianca_minima_sombra=0.7, confianca_minima_automatico=0.95,
    )

    candidatos = _selecionar_candidatos_banco(0, df_erp, df_banco, df_banco.index, config)

    # A configuração manual acima não pode contornar a trava de mesma data.
    assert candidatos == [0, 1, 2]


# ---------------------------------------------------------------------------
# _elegivel_para_ia
# ---------------------------------------------------------------------------


def _linha_revisao_manual(df_erp, i, motivo_revisao):
    return _linha_resultado_erp(
        df_erp.loc[i], STATUS_REVISAO_MANUAL, "obs", "Revisão Manual", None, None, None, None,
        motivo_revisao=motivo_revisao,
    )


def test_elegivel_quando_todos_os_criterios_batem():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00, favorecido="Fornecedor Ambíguo")
    linha = _linha_revisao_manual(df_erp, 0, MOTIVO_MULTIPLOS_CANDIDATOS)

    assert _elegivel_para_ia(linha, df_erp) is True


def test_nao_elegivel_quando_status_nao_e_revisao_manual():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    linha = _linha_resultado_erp(
        df_erp.loc[0], STATUS_CONCILIADO, "", "Valor e data", date(2026, 6, 10), -500.00, "X", 0,
    )

    assert _elegivel_para_ia(linha, df_erp) is False


def test_nao_elegivel_quando_origem_e_banco():
    from src.conciliador import _linha_resultado_banco

    df_banco = construir_df_banco([{"data": date(2026, 6, 10), "valor": -500.00, "favorecido": "X"}])
    linha = _linha_resultado_banco(
        df_banco.loc[0], STATUS_REVISAO_MANUAL, "obs", "Revisão Manual", None, "", None, None, None,
        motivo_revisao=MOTIVO_MULTIPLOS_CANDIDATOS,
    )

    assert _elegivel_para_ia(linha, df_banco) is False


def test_nao_elegivel_quando_motivo_fora_da_lista_branca():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00)
    for motivo in (
        MOTIVO_QUANTIDADE_DIVERGENTE,
        MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA,
        MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO,
        MOTIVO_SEM_DATA_PAGAMENTO,
        MOTIVO_REMUNERACAO_SEM_NOME,
    ):
        linha = _linha_revisao_manual(df_erp, 0, motivo)
        assert _elegivel_para_ia(linha, df_erp) is False, motivo


def test_nao_elegivel_quando_e_tipo_lote():
    df_erp = _erp_unico(date(2026, 6, 10), 500.00, favorecido="Pagamento de Salário Fulano")
    linha = _linha_revisao_manual(df_erp, 0, MOTIVO_NOME_INSUFICIENTE)

    assert _elegivel_para_ia(linha, df_erp) is False


def test_nao_elegivel_quando_data_erp_usada_nula():
    df_erp = construir_df_erp([
        {"data_usada": None, "valor": 500.00, "favorecido": "Fornecedor Sem Data"},
    ])
    linha = _linha_revisao_manual(df_erp, 0, MOTIVO_MULTIPLOS_CANDIDATOS)

    assert _elegivel_para_ia(linha, df_erp) is False
