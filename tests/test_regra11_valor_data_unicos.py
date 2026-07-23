"""Regra revisada em 2026-07-10-d (ver docs/HISTORICO_DECISOES.md): antes de
finalizar um ERP como "Não encontrado no banco", se existir banco disponível
com o mesmo valor absoluto e a mesma Data Banco, e esse par for único dos dois
lados (nenhum outro ERP/Banco concorrendo pelo mesmo valor/data), o sistema
concilia automaticamente por "Valor e data" — sem exigir nome/descrição
compatível, porque valor+data já bastam para identificar o par sem ambiguidade
operacional.

Caso real que motivou a mudança: "FGTS - RESCISÃO DANIEL LEMOS" (ERP) batendo
em valor e data com "PIX QR CODE DINAMICO DES: CEF MATRIZ" (banco) — o texto
do banco nunca menciona o nome do funcionário (o FGTS é depositado direto na
Caixa Econômica Federal), então não havia nenhum termo em comum, e a trava de
"remuneração sem nome antes do lote" bloqueava a conciliação automática mesmo
sem existir nenhum lote NET EMP por perto. Corrigido classificando "FGTS" como
uma exclusão de tipo de lote (`PALAVRAS_EXCLUSAO_TIPO_LOTE_ERP`) — FGTS nunca
é pago via lote de folha da empresa.
"""

from datetime import date

import pandas as pd

from src.conciliador import (
    MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO,
    MOTIVO_NAO_ENCONTRADO_MULTIPLOS,
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    TIPO_VALOR_DATA_NOME,
    TIPO_VALOR_E_DATA,
    _classificar_tipo_lote,
    _verificar_possiveis_pares_nao_encontrados,
    conciliar,
)
from src.exportador import NOME_ABA_BASE_DETALHADA, NOME_ABA_RESUMO, exportar_resultado
from tests.conftest import construir_df_banco, construir_df_erp


def _com_valor_abs(df):
    df = df.copy()
    df["_valor_abs"] = df["Valor"].abs().round(2)
    return df


def test_fgts_rescisao_nao_e_classificado_como_lote():
    """FGTS nunca é lote, mesmo contendo "RESCISÃO"/"13" no texto (marcador de
    tipo de lote) — é sempre um depósito direto na Caixa Econômica Federal."""
    assert _classificar_tipo_lote("FGTS - RESCISAO DANIEL LEMOS") is None
    assert _classificar_tipo_lote("FGTS - 13a da 2a parcela") is None
    # Sem "FGTS", o mesmo texto continua sendo classificado normalmente.
    assert _classificar_tipo_lote("RESCISAO DANIEL LEMOS") is not None


def test_fgts_rescisao_daniel_lemos_concilia_por_valor_e_data(logger_silencioso):
    """Caso real: FGTS - Rescisão bate em valor/data com um PIX à Caixa
    (CEF), sem nenhum nome em comum — único dos dois lados, deve conciliar."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 3, 6), "valor": 2017.15, "favorecido": "FGTS - RESCISAO DANIEL LEMOS"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 3, 6), "valor": -2017.15, "favorecido": "PIX QR CODE DINAMICO DES: CEF MATRIZ 06/03"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 1
    assert resultado.iloc[0]["Status"] == STATUS_CONCILIADO
    assert resultado.iloc[0]["Tipo Conciliação"] == TIPO_VALOR_E_DATA
    assert resultado.iloc[0]["Origem"] == "ERP+Banco"


def test_erp_unico_banco_unico_descricao_diferente_concilia_por_valor_e_data(logger_silencioso):
    """Teste 4 do pedido: ERP único + banco único, mesmo valor/data, descrição
    totalmente diferente — deve conciliar por Valor e data (regra já existente
    para pares não-lote, confirmada aqui explicitamente)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 4, 12), "valor": 3456.10, "favorecido": "Consultoria Jurídica Silva & Associados"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 4, 12), "valor": -3456.10, "favorecido": "PAGTO ELETRON COBRANCA XPTO999"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 1
    assert resultado.iloc[0]["Status"] == STATUS_CONCILIADO
    assert resultado.iloc[0]["Tipo Conciliação"] == TIPO_VALOR_E_DATA


def test_erp_com_dois_bancos_mesmo_valor_data_vai_para_revisao_manual(logger_silencioso):
    """Teste 5 do pedido: ERP com mesmo valor/data que dois bancos — nunca
    escolhe um sozinho, tudo fica em Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 4, 20), "valor": 800.00, "favorecido": "Consultoria Diversos XPTO"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 4, 20), "valor": -800.00, "favorecido": "PAGTO ELETRON COBRANCA AAA111"},
        {"data": date(2026, 4, 20), "valor": -800.00, "favorecido": "PAGTO ELETRON COBRANCA BBB222"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert (resultado["Status"] != STATUS_CONCILIADO).all()


def test_dois_erp_mesmo_valor_data_um_banco_vai_para_revisao_manual(logger_silencioso):
    """Teste 6 do pedido: dois ERP com mesmo valor/data e um banco — nunca
    escolhe um sozinho, tudo fica em Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 4, 21), "valor": 900.00, "favorecido": "Consultoria Alfa"},
        {"data_usada": date(2026, 4, 21), "valor": 900.00, "favorecido": "Consultoria Beta"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 4, 21), "valor": -900.00, "favorecido": "PAGTO ELETRON COBRANCA CCC333"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert (resultado["Status"] != STATUS_CONCILIADO).all()


def test_resultado_sem_pares_duplicados(logger_silencioso):
    """Teste 7 do pedido: Resultado.xlsx não pode ter pares duplicados."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 3, 6), "valor": 2017.15, "favorecido": "FGTS - RESCISAO DANIEL LEMOS"},
        {"data_usada": date(2026, 5, 28), "valor": 700.00, "favorecido": "PROV-088/2026 Mauro Vagner"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 3, 6), "valor": -2017.15, "favorecido": "PIX QR CODE DINAMICO DES: CEF MATRIZ 06/03"},
        {"data": date(2026, 5, 28), "valor": -700.00, "favorecido": "PIX ENVIADO DES: MAURO VAGNER DA COSTA 28/05"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 2
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Origem"] == "ERP+Banco").all()
    assert not resultado.duplicated(subset=["Descrição ERP", "Descrição Banco"], keep=False).any()


def test_resultado_xlsx_tem_apenas_uma_aba(tmp_path, logger_silencioso):
    """Teste 8 do pedido: Resultado.xlsx deve ter apenas 1 aba, "Resultado"."""
    import openpyxl

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 3, 6), "valor": 2017.15, "favorecido": "FGTS - RESCISAO DANIEL LEMOS"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 3, 6), "valor": -2017.15, "favorecido": "PIX QR CODE DINAMICO DES: CEF MATRIZ 06/03"},
    ])
    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    caminho = tmp_path / "Resultado.xlsx"
    exportar_resultado(resultado, caminho, logger_silencioso)

    workbook = openpyxl.load_workbook(caminho, read_only=True)
    assert workbook.sheetnames == [NOME_ABA_RESUMO, NOME_ABA_BASE_DETALHADA] == ["Resumo", "Base Detalhada"]


# ---------------------------------------------------------------------------
# Testes diretos de _verificar_possiveis_pares_nao_encontrados (verificação
# final antes de "Não encontrado no banco") — cobrem precisamente os casos B/C
# do pedido (múltiplos candidatos, banco já consumido) e o caso A (único, sem
# nome) neste ponto específico do pipeline.
# ---------------------------------------------------------------------------


def test_recuperacao_concilia_candidato_unico_por_valor_data_sem_nome(logger_silencioso):
    df_erp = _com_valor_abs(construir_df_erp([
        {"data_usada": date(2026, 6, 1), "valor": 4321.55, "favorecido": "Fornecedor Sem Nome Compatível"},
    ]))
    df_banco = _com_valor_abs(construir_df_banco([
        {"data": date(2026, 6, 1), "valor": -4321.55, "favorecido": "PIX QR CODE DINAMICO DES: CEF MATRIZ"},
    ]))

    linhas, erp_reclass, banco_reclass = _verificar_possiveis_pares_nao_encontrados(
        df_erp, df_banco, list(df_erp.index), list(df_banco.index), logger_silencioso,
    )

    assert erp_reclass == set(df_erp.index)
    assert banco_reclass == set(df_banco.index)
    status_por_origem = {linha["Origem"]: linha["Status"] for linha in linhas}
    assert status_por_origem == {"ERP": STATUS_CONCILIADO, "Banco": STATUS_CONCILIADO}
    assert all(linha["Tipo Conciliação"] == TIPO_VALOR_E_DATA for linha in linhas)


def test_recuperacao_nao_concilia_quando_ha_multiplos_candidatos_por_valor_data(logger_silencioso):
    df_erp = _com_valor_abs(construir_df_erp([
        {"data_usada": date(2026, 6, 2), "valor": 555.00, "favorecido": "Fornecedor Ambíguo"},
    ]))
    df_banco = _com_valor_abs(construir_df_banco([
        {"data": date(2026, 6, 2), "valor": -555.00, "favorecido": "PAGTO ELETRON COBRANCA AAA"},
        {"data": date(2026, 6, 2), "valor": -555.00, "favorecido": "PAGTO ELETRON COBRANCA BBB"},
    ]))

    linhas, erp_reclass, banco_reclass = _verificar_possiveis_pares_nao_encontrados(
        df_erp, df_banco, list(df_erp.index), list(df_banco.index), logger_silencioso,
    )

    assert len(linhas) == 1
    assert linhas[0]["Status"] == STATUS_REVISAO_MANUAL
    assert linhas[0]["Motivo Revisão"] == MOTIVO_NAO_ENCONTRADO_MULTIPLOS
    assert banco_reclass == set()


def test_recuperacao_nao_concilia_quando_banco_ja_consumido(logger_silencioso):
    df_erp = _com_valor_abs(construir_df_erp([
        {"data_usada": date(2026, 6, 3), "valor": 777.00, "favorecido": "Fornecedor Já Sem Sorte"},
    ]))
    df_banco = _com_valor_abs(construir_df_banco([
        {"data": date(2026, 6, 3), "valor": -777.00, "favorecido": "PAGTO ELETRON COBRANCA CCC"},
    ]))
    # `indices_banco_finais` vazio simula o banco já ter sido consumido por
    # outro lançamento em uma fase anterior (não está mais "pendente").
    linhas, erp_reclass, banco_reclass = _verificar_possiveis_pares_nao_encontrados(
        df_erp, df_banco, list(df_erp.index), [], logger_silencioso,
    )

    assert len(linhas) == 1
    assert linhas[0]["Status"] == STATUS_REVISAO_MANUAL
    assert linhas[0]["Motivo Revisão"] == MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO
    assert linhas[0]["Status do Possível Banco"] == "Já consumido por outro lançamento"
