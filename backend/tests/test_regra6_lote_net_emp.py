"""Regra 6 (CLAUDE.md): lançamentos NET EMP / NET EMPR.

- "PGTO SALARIO VIA NET EMP" (e variações) nunca devem ser conciliados
  individualmente por valor e data, mesmo quando por coincidência um único
  lançamento do ERP bate exatamente com o valor e a data;
- devem ser reservados para a etapa de lote;
- se a soma dos lançamentos do ERP ainda não conciliados bater exatamente com
  a soma dos lançamentos NET EMP do banco na mesma data, conciliar por lote
  (total direto), com o mesmo ID Lote nos dois lados, cada lançamento em sua
  própria linha.
"""

from datetime import date

from src.conciliador import (
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    TIPO_CONCILIACAO_LOTE_CONSOLIDADO,
    TIPO_VALOR_DATA_DESCRICAO,
    TIPO_VALOR_DATA_NOME,
    TIPO_VALOR_DATA_TOLERANCIA,
    TIPO_VALOR_E_DATA,
    MOTIVO_LOTE_DIVERGENCIA_DATA,
    MOTIVO_LOTE_ERP_MENOR_QUE_BANCO,
    MOTIVO_REMUNERACAO_SEM_NOME,
    MOTIVO_TOLERANCIA_SEM_EVIDENCIA,
    _e_candidato_lote_banco,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp


def test_net_emp_nao_concilia_por_valor_e_data_mesmo_coincidindo(logger_silencioso):
    """Mesmo quando existe só 1 lançamento do ERP e 1 do banco com valor e data
    idênticos, um lançamento NET EMP nunca pode ser marcado "Valor e data" — a
    passagem obrigatória é pela etapa de lote."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 26), "valor": 1500.00, "favorecido": "REMUNERAÇÃO - Funcionário Único"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 26), "valor": -1500.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Tipo Conciliação"] != TIPO_VALOR_E_DATA).all()
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()


def test_lote_concilia_quando_soma_do_erp_bate_com_soma_do_banco(logger_silencioso):
    """Exemplo do CLAUDE.md: vários pagamentos restantes do ERP cuja soma bate
    exatamente com o total dos PGTO ... VIA NET EMP do banco na mesma data
    (Etapa A: total direto)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 12), "valor": 7393.97, "favorecido": "Férias - Brunno de Andrade"},
        {"data_usada": date(2026, 5, 12), "valor": 7408.15, "favorecido": "Férias - Yan Esteves"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 12), "valor": -14802.12, "favorecido": "PGTO FERIAS VIA NET EMPR"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()

    # 2 lançamentos do ERP + 1 do banco = 3 linhas, cada uma individual (não é
    # par 1-para-1, então não é mesclada pela Regra 1 — cada lançamento
    # continua com sua própria linha, como sempre).
    assert len(resultado) == 3
    ids_lote = resultado["ID Lote"].unique()
    assert len(ids_lote) == 1
    assert ids_lote[0].startswith("FERIAS-2026-05-12")
    assert (resultado[resultado["Origem"] == "ERP"].shape[0]) == 2
    assert (resultado[resultado["Origem"] == "Banco"].shape[0]) == 1


def test_lote_fica_em_revisao_manual_quando_erp_menor_que_banco(logger_silencioso):
    """Quando o total do ERP é menor que o total do banco, nenhuma etapa
    automática pode fechar o lote (não há como "inventar" candidato) — fica em
    Revisão Manual com o motivo específico."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Fulano"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 6), "valor": -1500.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].str.startswith(MOTIVO_LOTE_ERP_MENOR_QUE_BANCO).all()
    assert resultado["ID Lote"].isna().all()
    # O detalhe que antes só existia na aba de diagnóstico (diferença, etapa
    # que falhou) agora vem embutido no próprio Motivo Revisão (Regra 2).
    assert resultado["Motivo Revisão"].str.contains("diferença R\\$ -500.00", na=False).all()


def test_net_empresa_generico_nao_vira_lote(logger_silencioso):
    """Correção: "NET EMPRESA" sozinho, sem termo de tipo claro (salário,
    férias, rescisão, folha ou 13º), não pode ser tratado como lote — ex.:
    "PAGTO ELETRON COBRANCA PAG COBRANCA NET EMPRESA" é um pagamento comum e
    deve seguir a conciliação individual normal (valor + data)."""
    assert _e_candidato_lote_banco("PAGTO ELETRON COBRANCA PAG COBRANCA NET EMPRESA") is False
    assert _e_candidato_lote_banco("PAG COBRANCA NET EMPRESA") is False

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 20), "valor": 850.00, "favorecido": "Fornecedor Eletrônica XYZ"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 20), "valor": -850.00, "favorecido": "PAGTO ELETRON COBRANCA PAG COBRANCA NET EMPRESA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_E_DATA).all()
    assert resultado["ID Lote"].isna().all()


def test_erp_salario_nao_vira_revisao_manual_por_coincidencia_antes_do_lote(logger_silencioso):
    """Correção: um lançamento de REMUNERAÇÃO/SALÁRIO do ERP não pode ser
    consumido por uma coincidência de valor+data com um lançamento comum do
    banco (virando "Revisão Manual" por duplicidade/nome insuficiente) antes
    de a etapa de lote ter a chance de fechar a soma — mesmo quando isso cria
    um grupo ambíguo na conciliação individual (dias 06/05 e 26/05, replicando
    o problema relatado com dados reais)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - João Silva"},
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "REMUNERAÇÃO - Maria Souza"},
        {"data_usada": date(2026, 5, 26), "valor": 2200.00, "favorecido": "REMUNERAÇÃO - Carlos Pereira"},
        {"data_usada": date(2026, 5, 26), "valor": 1800.00, "favorecido": "REMUNERAÇÃO - Ana Lima"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 6), "valor": -2000.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
        {"data": date(2026, 5, 6), "valor": -1000.00, "favorecido": "PAGAMENTO FORNECEDOR ABC LTDA"},
        {"data": date(2026, 5, 26), "valor": -4000.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    salarios = resultado[resultado["Descrição ERP"].str.contains("REMUNERAÇÃO", na=False)]
    assert (salarios["Status"] == STATUS_CONCILIADO).all()
    assert (salarios["Tipo Conciliação"] == TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()

    # 2 lotes (06/05 e 26/05), cada um com 2 candidatos ERP e 1 lançamento do
    # banco — verificado direto pelas linhas do Resultado (não há mais aba de
    # diagnóstico de lote, ver Regra 2).
    ids_lote_salario = resultado.loc[resultado["ID Lote"].str.startswith("SALARIO", na=False), "ID Lote"].unique()
    assert len(ids_lote_salario) == 2
    for id_lote in ids_lote_salario:
        grupo = resultado[resultado["ID Lote"] == id_lote]
        assert (grupo["Status"] == STATUS_CONCILIADO).all()
        assert (grupo[grupo["Origem"] == "ERP"].shape[0]) == 2
        assert (grupo[grupo["Origem"] == "Banco"].shape[0]) == 1


def test_pagamento_individual_nomeado_sai_do_pool_do_lote_antes_da_soma(logger_silencioso):
    """Reordenação de 2026-07-10 (docs/HISTORICO_DECISOES.md): um funcionário de
    Salário/Folha pago individualmente (PIX nomeado), com o mesmo valor e data
    de dois colegas que de fato formam o lote NET EMP, deve ser conciliado pela
    via individual (descrição/nome) e sair do pool do lote ANTES da soma —
    reproduz em miniatura o caso real de 06/05/2026 (29 candidatos -> 20 depois
    de tirar quem foi pago fora do lote, fechando por total direto)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "Remuneração - João Silva"},
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "Remuneração - Maria Souza"},
        {"data_usada": date(2026, 5, 6), "valor": 1000.00, "favorecido": "Remuneração - Carlos Pereira"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 6), "valor": -2000.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
        {"data": date(2026, 5, 6), "valor": -1000.00, "favorecido": "PIX ENVIADO DES: CARLOS PEREIRA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    carlos = resultado[resultado["Descrição ERP"].str.contains("Carlos", na=False)]
    assert (carlos["Status"] == STATUS_CONCILIADO).all()
    assert (carlos["Tipo Conciliação"] == TIPO_VALOR_DATA_DESCRICAO).all()
    assert carlos["ID Lote"].isna().all()

    joao_maria = resultado[resultado["Descrição ERP"].str.contains("João|Maria", na=False)]
    assert (joao_maria["Status"] == STATUS_CONCILIADO).all()
    assert (joao_maria["Tipo Conciliação"] == TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()
    assert joao_maria["ID Lote"].nunique() == 1
    # Só João e Maria (2 candidatos) fecham o lote por total direto — Carlos
    # já saiu do pool antes, via conciliação individual por nome/descrição.
    # O detalhe granular de quantos candidatos existiam antes/depois da
    # conciliação individual (3 antes, 1 já conciliado, 2 restantes) agora só
    # fica no log (Regra 2, 2026-07-10-b) — o resultado observável (quem
    # fechou o lote e quem não) já está garantido pelas asserções acima.
    assert (joao_maria[joao_maria["Origem"] == "ERP"].shape[0]) == 2


# ---------------------------------------------------------------------------
# Regra global de 2026-07-23: lote e pagamento individual exigem a mesma data.
# Remuneração também não pode ser consumida antes do lote só por valor+data.
# ---------------------------------------------------------------------------


def test_net_emp_nao_fecha_com_data_diferente_mesmo_por_1_dia(logger_silencioso):
    """Lote NET EMP não usa tolerância de data nenhuma: um candidato do ERP 1
    dia antes/depois da data do lote bancário não pode fechar automaticamente
    — fica em Revisão Manual com motivo de divergência de data."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 2), "valor": 1000.00, "favorecido": "Remuneração - Fulano"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 1), "valor": -1000.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Motivo Revisão"].str.startswith(MOTIVO_LOTE_DIVERGENCIA_DATA).all()
    assert resultado["ID Lote"].isna().all()
    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert erp_linha["Motivo Revisão"].str.contains("não coincide com nenhuma data de lote", na=False).all()


def test_pagamento_individual_com_um_dia_de_diferenca_nao_concilia(logger_silencioso):
    """Mesmo com nome e valor compatíveis, datas diferentes não conciliam."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 500.00, "favorecido": "Fornecedor Alfa Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 11), "valor": -500.00, "favorecido": "PAGTO FORNECEDOR ALFA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    erp_linha = resultado[resultado["Origem"] == "ERP"]
    banco_linha = resultado[resultado["Origem"] == "Banco"]
    assert (erp_linha["Status"] == STATUS_REVISAO_MANUAL).all()
    assert erp_linha["Motivo Revisão"].str.contains("mesma data", case=False, na=False).all()
    assert (banco_linha["Status"] == "Somente banco").all()


def test_pagamento_individual_data_diferente_sem_nome_vai_para_revisao_manual(logger_silencioso):
    """Candidato único em outra data e sem nome compatível não concilia."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 15), "valor": 700.00, "favorecido": "Consultoria XPTO 123"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 16), "valor": -700.00, "favorecido": "PAGTO ELETRON COBRANCA ZZZ999"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert (erp_linha["Status"] == STATUS_REVISAO_MANUAL).all()
    assert erp_linha["Motivo Revisão"].str.contains("mesma data", case=False, na=False).all()


def test_pagamento_individual_2_dias_de_diferenca_nao_concilia_automaticamente(logger_silencioso):
    """Qualquer diferença de data bloqueia a conciliação. O possível par fica
    visível em Revisão Manual com motivo explícito, sem desaparecer."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 20), "valor": 300.00, "favorecido": "Fornecedor Beta"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 22), "valor": -300.00, "favorecido": "PAGTO FORNECEDOR BETA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    # Só o lado ERP é reclassificado por essa verificação (regra 2026-07-10 é
    # centrada no ERP); o banco pendente continua "Somente banco" normalmente.
    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert (erp_linha["Status"] == STATUS_REVISAO_MANUAL).all()
    assert erp_linha["Motivo Revisão"].str.contains("mesma data", case=False, na=False).all()


def test_remuneracao_sem_nome_e_sem_lote_ativo_vai_para_revisao_manual(logger_silencioso):
    """Um lançamento de remuneração que bate em valor+data com um pagamento
    comum do banco, sem nenhum sinal de nome/descrição em comum e sem nenhum
    lote NET EMP ativo naquela data, nunca pode ser conciliado automaticamente
    só por valor+data — vai para Revisão Manual."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 25), "valor": 900.00, "favorecido": "Remuneração - Setor Financeiro"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 25), "valor": -900.00, "favorecido": "PAGTO ELETRON COBRANCA XYZ777"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert (resultado["Motivo Revisão"] == MOTIVO_REMUNERACAO_SEM_NOME).all()


def test_remuneracao_sem_nome_mas_com_lote_ativo_fica_disponivel_para_o_lote(logger_silencioso):
    """Quando existe um lote NET EMP claro do mesmo tipo na mesma data exata, um
    lançamento de remuneração que colide por coincidência com um pagamento
    comum do banco (sem nome em comum) não é finalizado ali — fica disponível
    para a etapa de lote, que fecha por total direto; o pagamento comum vira
    Revisão Manual (não "rouba" nem "é roubado")."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 7, 1), "valor": 800.00, "favorecido": "Remuneração - Setor TI"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 7, 1), "valor": -800.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
        {"data": date(2026, 7, 1), "valor": -800.00, "favorecido": "PAGTO ELETRON COBRANCA QWE111"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    # 1 ERP x 1 Banco fecha o lote por total direto — a Regra 1 (2026-07-10-b)
    # mescla esse par 1-para-1 numa única linha (Origem="ERP+Banco"). Filtra
    # por Status=Conciliado porque a linha do banco individual ambíguo (que
    # NÃO fechou com este ERP) também referencia "Remuneração - Setor TI"
    # como possível par nas suas colunas — mas fica em Revisão Manual.
    setor_ti = resultado[
        (resultado["Descrição ERP"] == "Remuneração - Setor TI") & (resultado["Status"] == STATUS_CONCILIADO)
    ]
    assert len(setor_ti) == 1
    assert (setor_ti["Status"] == STATUS_CONCILIADO).all()
    assert (setor_ti["Tipo Conciliação"] == TIPO_CONCILIACAO_LOTE_CONSOLIDADO).all()
    assert (setor_ti["Origem"] == "ERP+Banco").all()

    banco_individual = resultado[resultado["Descrição Banco"] == "PAGTO ELETRON COBRANCA QWE111"]
    assert (banco_individual["Status"] == STATUS_REVISAO_MANUAL).all()
    assert (banco_individual["Motivo Revisão"] == MOTIVO_REMUNERACAO_SEM_NOME).all()


def test_remuneracao_com_nome_compativel_concilia_par_unico(logger_silencioso):
    """Um par único remuneração x pagamento individual com nome/descrição
    compatível pode conciliar direto — a trava só se aplica quando falta esse
    sinal."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 7, 5), "valor": 650.00, "favorecido": "Remuneração - Pedro Alves Nogueira"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 7, 5), "valor": -650.00, "favorecido": "PIX ENVIADO DES: PEDRO ALVES NOGUEIRA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_DATA_NOME).all()
