"""Regra revisada em 2026-07-10 (ver docs/HISTORICO_DECISOES.md): antes de
finalizar um lançamento do ERP como "Não encontrado no banco", o sistema
verifica se existe um possível par no banco (usado ou não) por valor
absoluto + data + nome/descrição — só sobre o que sobrou depois de todas as
fases principais (individual, tolerância, lote), para nunca interferir nelas.

Nunca força conciliação quando há risco: só concilia quando o candidato é
único dos dois lados, tem nome/descrição forte compatível e ainda está
pendente; qualquer outro indício vira Revisão Manual com motivo específico,
nunca "Não encontrado no banco" sem explicação.

Regra 2 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): não existe mais uma
aba/DataFrame de diagnóstico separado — as colunas "Motivo Não Conciliado",
"Possível Data/Valor/Descrição Banco" e "Status do Possível Banco" já vêm
preenchidas na própria linha do Resultado.
"""

from datetime import date

from src.conciliador import (
    STATUS_CONCILIADO,
    STATUS_NAO_ENCONTRADO_BANCO,
    STATUS_REVISAO_MANUAL,
    MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO,
    MOTIVO_NAO_ENCONTRADO_MULTIPLOS,
    conciliar,
)
from tests.conftest import construir_df_banco, construir_df_erp


def test_mauro_vagner_concilia_por_nome_forte(logger_silencioso):
    """Caso A do pedido: ERP único + banco único + mesma data + mesmo valor +
    nome forte compatível -> Conciliado."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 28), "valor": 700.00, "favorecido": "PROV-088/2026 Mauro Vagner"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 28), "valor": -700.00, "favorecido": "PIX ENVIADO DES: MAURO VAGNER DA COSTA 28/05"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    # Par 1-para-1: a Regra 1 mescla numa única linha (Origem="ERP+Banco").
    assert len(resultado) == 1
    assert resultado.iloc[0]["Origem"] == "ERP+Banco"


def test_heros_rampazzo_concilia_por_descricao_parecida(logger_silencioso):
    """Caso B do pedido: ERP único + banco único + mesma data + mesmo valor +
    descrição parecida -> Conciliado."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 28), "valor": 100.00, "favorecido": "PROV-087/2026 Heros Rampazzo"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 28), "valor": -100.00, "favorecido": "PIX ENVIADO DES: HEROS RAMPAZZO PINTO 28/05"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert len(resultado) == 1
    assert resultado.iloc[0]["Origem"] == "ERP+Banco"


def test_multiplos_bancos_possiveis_mantem_revisao_manual(logger_silencioso):
    """Teste 5 do pedido: ERP com mesmo valor e data de vários bancos possíveis
    (aqui, dois lançamentos de lote reservados que nunca chegam à fase 1) —
    nunca escolhe um sozinho, fica em Revisão Manual com motivo específico."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 5), "valor": 1200.00, "favorecido": "Fornecedor Ambíguo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 5), "valor": -1200.00, "favorecido": "PGTO SALARIO VIA NET EMP"},
        {"data": date(2026, 6, 5), "valor": -1200.00, "favorecido": "PGTO FERIAS VIA NET EMP"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert len(erp_linha) == 1
    assert (erp_linha["Status"] == STATUS_REVISAO_MANUAL).all()
    assert erp_linha["Motivo Revisão"].str.contains(MOTIVO_NAO_ENCONTRADO_MULTIPLOS, na=False).all()


def test_banco_ja_consumido_por_lote_registra_diagnostico_sem_trocar(logger_silencioso):
    """Caso E do pedido: um ERP comum (não-lote) coincide em valor+data+nome
    com um banco NET EMP que, na verdade, já fechou um lote com outro
    lançamento do ERP — o sistema NUNCA desfaz a conciliação do lote para
    "roubar" o banco; só registra o conflito na própria linha."""
    df_erp = construir_df_erp([
        # Fecha o lote por total direto (mesmo valor do banco NET EMP).
        {"data_usada": date(2026, 6, 15), "valor": 650.00, "favorecido": "Remuneração - Ana Beatriz"},
        # Não é lote-type: nunca compete pelo banco NET EMP na fase 1/2/lote,
        # só encontra a coincidência na verificação final.
        {"data_usada": date(2026, 6, 15), "valor": 650.00, "favorecido": "Zeca Pagodinho Doações"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 15), "valor": -650.00, "favorecido": "PGTO SALARIO VIA NET EMP ZECA PAGODINHO"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    ana = resultado[resultado["Descrição ERP"] == "Remuneração - Ana Beatriz"]
    assert (ana["Status"] == STATUS_CONCILIADO).all()

    zeca = resultado[(resultado["Descrição ERP"] == "Zeca Pagodinho Doações") & (resultado["Origem"] == "ERP")]
    assert (zeca["Status"] == STATUS_REVISAO_MANUAL).all()
    assert (zeca["Motivo Revisão"] == MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO).all()
    assert (zeca["Status do Possível Banco"] == "Já consumido por outro lançamento").all()
    assert (zeca["Possível Descrição Banco"] == "PGTO SALARIO VIA NET EMP ZECA PAGODINHO").all()


def test_diagnostico_nao_encontrados_lista_mesmo_sem_candidato_nenhum(logger_silencioso):
    """Um ERP genuinamente sem nenhum candidato bancário continua "Não
    encontrado no banco", mas a própria linha traz o motivo em "Motivo Não
    Conciliado", para nunca ficar "sem explicação"."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 30), "valor": 9999.99, "favorecido": "Fornecedor Totalmente Sem Par"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 1), "valor": -50.00, "favorecido": "PAGTO OUTRO FORNECEDOR QUALQUER"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert len(erp_linha) == 1
    assert (erp_linha["Status"] == STATUS_NAO_ENCONTRADO_BANCO).all()
    assert "Nenhum lançamento bancário" in erp_linha.iloc[0]["Motivo Não Conciliado"]
