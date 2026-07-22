"""Regra revisada em 2026-07-10-c (ver docs/HISTORICO_DECISOES.md): grupos com
mesmo valor absoluto e mesma data (ou dentro da tolerância de 1 dia) devem
tentar pareamento por nome/descrição antes de mandar tudo para Revisão Manual.

O bug real relatado pelo usuário (ex.: "Distribuição de Lucros" gerando
combinações cruzadas como "Ricardo Mouro x Raphael Pekly") acontecia na fase
de TOLERÂNCIA (`_resolver_correspondencias_por_tolerancia`), que usava
ingenuamente `candidatos[0]` (o primeiro candidato da lista) em vez do
algoritmo de pareamento mutuamente único já existente para grupos de mesma
data exata. Corrigido reaproveitando `_desempatar_por_nome` (agora com suporte
a `pares_permitidos`, restringindo a comparação aos pares dentro da janela de
tolerância) também na fase de tolerância.

Também foi ampliada a pontuação de nome (`_termos_correspondentes`) para
aceitar truncamento (ex.: "SILV" compatível com "SILVA", "ALM" compatível com
"ALMEIDA") e a lista de palavras genéricas ignoradas (CC, PARA, DISTRIBUICAO,
LUCROS, TRANSFERENCIA, SALARIO, FOLHA, FERIAS, RESCISAO) em `src/utils.py`.
"""

from datetime import date

from src.conciliador import (
    MOTIVO_EMPATE_NOME,
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    TIPO_VALOR_DATA_NOME,
    TIPO_VALOR_DATA_TOLERANCIA,
    TIPO_VALOR_E_DATA,
    conciliar,
)
from src.exportador import NOME_ABA_RESULTADO, exportar_resultado
from tests.conftest import construir_df_banco, construir_df_erp

DISTRIBUICAO_LUCROS_ERP = [
    {"favorecido": "DISTRIBUICAO DE LUCROS RICARDO MOURO", "valor": 15000.00},
    {"favorecido": "DISTRIBUICAO DE LUCROS RAPHAEL PEKLY", "valor": 15000.00},
    {"favorecido": "DISTRIBUICAO DE LUCROS RAFAEL SILVA", "valor": 15000.00},
    {"favorecido": "DISTRIBUICAO DE LUCROS CLAUDIO ALMEIDA", "valor": 15000.00},
]
DISTRIBUICAO_LUCROS_BANCO = [
    {"favorecido": "PIX ENVIADO DES: Ricardo Bastos Mouro", "valor": -15000.00},
    {"favorecido": "TRANSF CC PARA CC RAPHAEL CABRAL PEKLY LUZ", "valor": -15000.00},
    {"favorecido": "PIX ENVIADO DES: RAFAEL SANTOS DA SILV", "valor": -15000.00},
    {"favorecido": "TRANSF CC PARA CC CLAUDIO EDIMILSON PEREIRA DE ALM", "valor": -15000.00},
]


def test_valor_e_data_unicos_concilia_automaticamente(logger_silencioso):
    """Teste 1 do pedido: ERP único + banco único com mesmo valor/data deve
    conciliar direto por "Valor e data" (regra já existente, sem mudança)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 4), "valor": 353.00, "favorecido": "Fornecedor Único Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 4), "valor": -353.00, "favorecido": "PAGTO FORNECEDOR QUALQUER"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 1
    assert resultado.iloc[0]["Status"] == STATUS_CONCILIADO
    assert resultado.iloc[0]["Tipo Conciliação"] == TIPO_VALOR_E_DATA


def test_distribuicao_de_lucros_mesma_data_concilia_por_nome(logger_silencioso):
    """Teste 2 do pedido: 4 ERP e 4 bancos com mesmo valor/data (mesma data
    exata dos dois lados), nomes distintos — cada par deve conciliar por
    "Valor, data e nome", nunca com combinação cruzada."""
    data = date(2026, 1, 29)
    df_erp = construir_df_erp([{"data_usada": data, **item} for item in DISTRIBUICAO_LUCROS_ERP])
    df_banco = construir_df_banco([{"data": data, **item} for item in DISTRIBUICAO_LUCROS_BANCO])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 4
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_DATA_NOME).all()
    assert (resultado["Origem"] == "ERP+Banco").all()

    pares_esperados = {
        "DISTRIBUICAO DE LUCROS RICARDO MOURO": "Ricardo Bastos Mouro",
        "DISTRIBUICAO DE LUCROS RAPHAEL PEKLY": "RAPHAEL CABRAL PEKLY LUZ",
        "DISTRIBUICAO DE LUCROS RAFAEL SILVA": "RAFAEL SANTOS DA SILV",
        "DISTRIBUICAO DE LUCROS CLAUDIO ALMEIDA": "CLAUDIO EDIMILSON PEREIRA DE ALM",
    }
    for descricao_erp, trecho_banco in pares_esperados.items():
        linha = resultado[resultado["Descrição ERP"] == descricao_erp]
        assert len(linha) == 1
        assert trecho_banco.upper() in linha.iloc[0]["Descrição Banco"].upper()


def test_distribuicao_de_lucros_com_um_dia_de_diferenca_concilia_por_tolerancia(logger_silencioso):
    """Caso real que gerava combinações cruzadas: ERP datado 1 dia depois do
    banco (fase de tolerância, não de data exata) — antes da correção, a
    tolerância usava "candidatos[0]" ingênuo e produzia pares errados
    ("Ricardo Mouro x Raphael Pekly" etc.); agora usa o mesmo pareamento por
    nome mutuamente único."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 1, 29), **item} for item in DISTRIBUICAO_LUCROS_ERP
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 1, 28), **item} for item in DISTRIBUICAO_LUCROS_BANCO
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == 4
    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_DATA_TOLERANCIA).all()
    assert (resultado["Diferença de Dias"] == 1).all()

    ricardo = resultado[resultado["Descrição ERP"] == "DISTRIBUICAO DE LUCROS RICARDO MOURO"]
    assert "MOURO" in ricardo.iloc[0]["Descrição Banco"].upper()
    assert "PEKLY" not in ricardo.iloc[0]["Descrição Banco"].upper()


def test_grupo_parcialmente_resolvido_concilia_seguros_e_deixa_resto_em_revisao(logger_silencioso):
    """Teste 3 do pedido: de um grupo de 4, 3 pares têm nome claro e devem
    conciliar; o par restante (sem nenhum sinal de nome em comum) fica em
    Revisão Manual, sem travar os outros 3."""
    data = date(2026, 3, 10)
    df_erp = construir_df_erp([
        {"data_usada": data, "valor": 900.00, "favorecido": "DISTRIBUICAO DE LUCROS RICARDO MOURO"},
        {"data_usada": data, "valor": 900.00, "favorecido": "DISTRIBUICAO DE LUCROS RAPHAEL PEKLY"},
        {"data_usada": data, "valor": 900.00, "favorecido": "DISTRIBUICAO DE LUCROS RAFAEL SILVA"},
        {"data_usada": data, "valor": 900.00, "favorecido": "Consultoria Genérica XPTO"},
    ])
    df_banco = construir_df_banco([
        {"data": data, "valor": -900.00, "favorecido": "PIX ENVIADO DES: Ricardo Bastos Mouro"},
        {"data": data, "valor": -900.00, "favorecido": "TRANSF CC PARA CC RAPHAEL CABRAL PEKLY LUZ"},
        {"data": data, "valor": -900.00, "favorecido": "PIX ENVIADO DES: RAFAEL SANTOS DA SILV"},
        {"data": data, "valor": -900.00, "favorecido": "PAGTO ELETRON COBRANCA ZZZ999"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    conciliados = resultado[resultado["Status"] == STATUS_CONCILIADO]
    assert len(conciliados) == 3
    assert (conciliados["Tipo Conciliação"] == TIPO_VALOR_DATA_NOME).all()

    revisao = resultado[resultado["Status"] == STATUS_REVISAO_MANUAL]
    assert len(revisao) == 1  # a linha do ERP "Consultoria..." e a do banco "ZZZ999", cada uma na sua linha
    consultoria = revisao[revisao["Origem"] == "ERP"]
    assert (consultoria["Descrição ERP"] == "Consultoria Genérica XPTO").all()


def test_empate_de_nome_entre_multiplos_candidatos_mantem_revisao_manual(logger_silencioso):
    """Teste 5 do pedido: um ERP com dois bancos de pontuação igual (mesmo
    primeiro nome, nenhum sobrenome batendo) nunca escolhe um sozinho. Datado
    1 dia de diferença para exercitar a fase de tolerância (onde estava o bug
    real do "candidatos[0]" ingênuo) — o motivo específico de empate
    (`MOTIVO_EMPATE_NOME`) só existe nessa fase; a fase de data exata usa o
    motivo genérico já existente (`Duplicidade de valor e data...`)."""
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 4, 3), "valor": 500.00, "favorecido": "CARLOS MENDES"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 4, 2), "valor": -500.00, "favorecido": "PIX ENVIADO DES: CARLOS ALBERTO"},
        {"data": date(2026, 4, 2), "valor": -500.00, "favorecido": "PIX ENVIADO DES: CARLOS EDUARDO"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    erp_linha = resultado[resultado["Origem"] == "ERP"]
    assert (erp_linha["Motivo Revisão"] == MOTIVO_EMPATE_NOME).all()


def test_primeiro_nome_apenas_nao_concilia_automaticamente_com_risco_de_ambiguidade(logger_silencioso):
    """Teste 4 do pedido: "JOAO SILVA x JOAO PEREIRA" não deve conciliar
    automaticamente só por "JOAO" quando há risco real de ambiguidade — aqui,
    dois ERP e dois bancos começando por "JOAO", sem nenhum sobrenome batendo,
    formam um grupo genuinamente ambíguo (nunca escolhe um par sozinho)."""
    data = date(2026, 4, 15)
    df_erp = construir_df_erp([
        {"data_usada": data, "valor": 500.00, "favorecido": "JOAO SILVA"},
        {"data_usada": data, "valor": 500.00, "favorecido": "JOAO PEREIRA"},
    ])
    df_banco = construir_df_banco([
        {"data": data, "valor": -500.00, "favorecido": "PIX ENVIADO DES: JOAO SANTOS"},
        {"data": data, "valor": -500.00, "favorecido": "PIX ENVIADO DES: JOAO COSTA"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()
    assert resultado["Tipo Conciliação"].eq(TIPO_VALOR_DATA_NOME).sum() == 0


def test_resultado_sem_duplicidade_de_par(logger_silencioso):
    """Teste 6 do pedido: mesmo par ERP x Banco não pode aparecer duas vezes
    no Resultado (cada par conciliado vira 1 linha só, Regra 1 de 2026-07-10-b)."""
    data = date(2026, 1, 29)
    df_erp = construir_df_erp([{"data_usada": data, **item} for item in DISTRIBUICAO_LUCROS_ERP])
    df_banco = construir_df_banco([{"data": data, **item} for item in DISTRIBUICAO_LUCROS_BANCO])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert len(resultado) == len(DISTRIBUICAO_LUCROS_ERP)
    duplicados = resultado.duplicated(subset=["Descrição ERP", "Descrição Banco"], keep=False)
    assert not duplicados.any()


def test_resultado_xlsx_tem_apenas_uma_aba(tmp_path, logger_silencioso):
    """Teste 7 do pedido: Resultado.xlsx deve ter apenas 1 aba, "Resultado"."""
    import openpyxl

    data = date(2026, 1, 29)
    df_erp = construir_df_erp([{"data_usada": data, **item} for item in DISTRIBUICAO_LUCROS_ERP])
    df_banco = construir_df_banco([{"data": data, **item} for item in DISTRIBUICAO_LUCROS_BANCO])
    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    caminho = tmp_path / "Resultado.xlsx"
    exportar_resultado(resultado, caminho, logger_silencioso)

    workbook = openpyxl.load_workbook(caminho, read_only=True)
    assert workbook.sheetnames == [NOME_ABA_RESULTADO] == ["Resultado"]
