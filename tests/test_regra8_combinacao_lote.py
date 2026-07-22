"""Regra 8 (CLAUDE.md): quando o total de candidatos do ERP de um lote NET EMP
é maior que o total do banco, o sistema nunca adivinha quais pertencem ao
lote — tenta fechar automaticamente por combinação única de valores (Etapa B)
e, só quando o banco traz um identificador individual, por nome/descrição
(Etapa C). Não existe mais nenhuma marcação manual: a conciliação do lote é
sempre automática, baseada em evidência matemática ou de nome.
"""

from datetime import date

from src.conciliador import (
    MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO,
    MOTIVO_LOTE_MULTIPLAS_COMBINACOES,
    MOTIVO_LOTE_NENHUMA_COMBINACAO,
    STATUS_CONCILIADO,
    STATUS_NAO_ENCONTRADO_BANCO,
    STATUS_REVISAO_MANUAL,
    TIPO_LOTE_COMBINACAO_UNICA,
    TIPO_LOTE_POR_NOME,
    _banco_tem_identificador_individual,
    _buscar_combinacao_unica_centavos,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp


def test_buscar_combinacao_unica_centavos():
    itens = [(0, 1000_00), (1, 1200_00), (2, 800_00)]
    assert _buscar_combinacao_unica_centavos(itens, 2200_00) == ("UNICA", [0, 1])
    assert _buscar_combinacao_unica_centavos(itens, 999_99) == ("NENHUMA", None)

    itens_ambiguos = [(0, 500_00), (1, 500_00), (2, 500_00), (3, 500_00)]
    assert _buscar_combinacao_unica_centavos(itens_ambiguos, 1000_00) == ("MULTIPLAS", None)

    itens_grandes = [(i, 100) for i in range(50)]
    assert _buscar_combinacao_unica_centavos(itens_grandes, 100) == ("GRUPO_GRANDE", None)


def test_banco_tem_identificador_individual():
    assert _banco_tem_identificador_individual("PGTO SALARIO VIA NET EMP") is False
    assert _banco_tem_identificador_individual("PGTO FERIAS VIA NET EMPR") is False
    assert _banco_tem_identificador_individual("PGTO SALARIO VIA NET EMP JOAO SILVA") is True


def test_combinacao_unica_fecha_lote_automaticamente(logger_silencioso):
    """3 candidatos do ERP (Ana, Bruno, Carla), mas o banco só paga Ana+Bruno
    nesse lote — existe exatamente 1 combinação (Ana+Bruno) que soma o total
    do banco, então concilia sozinho; Carla fica de fora."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Ana"},
        {"data_usada": date(2026, 6, 10), "valor": 1200.00, "favorecido": "REMUNERAÇÃO - Bruno"},
        {"data_usada": date(2026, 6, 10), "valor": 800.00, "favorecido": "REMUNERAÇÃO - Carla"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -2200.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    ana_bruno = resultado[resultado["Descrição ERP"].isin(["REMUNERAÇÃO - Ana", "REMUNERAÇÃO - Bruno"])]
    assert (ana_bruno["Status"] == STATUS_CONCILIADO).all()
    assert (ana_bruno["Tipo Conciliação"] == TIPO_LOTE_COMBINACAO_UNICA).all()
    assert ana_bruno["ID Lote"].nunique() == 1

    carla = resultado[resultado["Descrição ERP"] == "REMUNERAÇÃO - Carla"]
    assert (carla["Status"] == STATUS_NAO_ENCONTRADO_BANCO).all()

    banco_linha = resultado[resultado["Origem"] == "Banco"]
    assert (banco_linha["Status"] == STATUS_CONCILIADO).all()
    assert banco_linha.iloc[0]["ID Lote"] == ana_bruno.iloc[0]["ID Lote"]


def test_multiplas_combinacoes_mantem_revisao_manual(logger_silencioso):
    """4 candidatos com o mesmo valor (500 cada) e o banco paga 1000 — existem
    várias duplas possíveis (500+500), então nunca adivinha: Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 15), "valor": 500.00, "favorecido": "REMUNERAÇÃO - Pessoa A"},
        {"data_usada": date(2026, 6, 15), "valor": 500.00, "favorecido": "REMUNERAÇÃO - Pessoa B"},
        {"data_usada": date(2026, 6, 15), "valor": 500.00, "favorecido": "REMUNERAÇÃO - Pessoa C"},
        {"data_usada": date(2026, 6, 15), "valor": 500.00, "favorecido": "REMUNERAÇÃO - Pessoa D"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 15), "valor": -1000.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].str.startswith(MOTIVO_LOTE_MULTIPLAS_COMBINACOES).all()
    assert resultado["ID Lote"].isna().all()


def test_banco_generico_sem_combinacao_mantem_revisao_manual(logger_silencioso):
    """Banco genérico (sem nome) e nenhum subconjunto do ERP soma o total do
    banco: nem combinação nem nome resolvem — Revisão Manual com o motivo
    específico de banco genérico."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 20), "valor": 333.33, "favorecido": "REMUNERAÇÃO - Fulano"},
        {"data_usada": date(2026, 6, 20), "valor": 900.00, "favorecido": "REMUNERAÇÃO - Beltrano"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 20), "valor": -999.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].str.startswith(MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO).all()


def test_etapa_c_resolve_por_nome_quando_banco_traz_identificador(logger_silencioso):
    """Quando o banco excepcionalmente traz nome junto do lote NET EMP, e a
    combinação por valor é ambígua (3 pessoas com o mesmo salário, banco só
    paga 2), o nome desempata com segurança quais delas pertencem ao lote."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 25), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Joao Silva"},
        {"data_usada": date(2026, 6, 25), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Maria Souza"},
        {"data_usada": date(2026, 6, 25), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Carlos Mendes"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 25), "valor": -1000.00, "favorecido": "PGTO SALARIO VIA NET EMP JOAO SILVA"},
        {"data": date(2026, 6, 25), "valor": -1000.00, "favorecido": "PGTO SALARIO VIA NET EMP MARIA SOUZA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    joao_maria = resultado[resultado["Descrição ERP"].str.contains("Joao|Maria", na=False)]
    assert (joao_maria["Status"] == STATUS_CONCILIADO).all()
    assert (joao_maria["Tipo Conciliação"] == TIPO_LOTE_POR_NOME).all()

    carlos = resultado[resultado["Descrição ERP"].str.contains("Carlos", na=False)]
    assert (carlos["Status"] == STATUS_NAO_ENCONTRADO_BANCO).all()

    banco_linhas = resultado[resultado["Origem"] == "Banco"]
    assert (banco_linhas["Status"] == STATUS_CONCILIADO).all()


def test_etapa_c_nao_resolve_quando_nome_nao_bate_com_nenhum_candidato(logger_silencioso):
    """Banco traz identificador, mas não corresponde a nenhum candidato do
    ERP: nome não resolve, combinação também não fecha -> Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 28), "valor": 700.00, "favorecido": "REMUNERAÇÃO - Pedro Alves"},
        {"data_usada": date(2026, 6, 28), "valor": 900.00, "favorecido": "REMUNERAÇÃO - Rita Nunes"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 28), "valor": -850.00, "favorecido": "PGTO SALARIO VIA NET EMP XPTO DESCONHECIDO"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].str.startswith(MOTIVO_LOTE_NENHUMA_COMBINACAO).all()
