"""Funções utilitárias reaproveitáveis entre os leitores de ERP e Banco."""

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

EXTENSOES_EXCEL = (".xlsx", ".xls")

# Palavras genéricas — tanto do lado do banco quanto do ERP — que não ajudam a
# diferenciar um lançamento do outro (usadas em normalizar_descricao). Remover
# essas palavras é o que permite comparar só o que sobra (nomes próprios,
# números de documento/provisão etc.).
# Ampliada em 2026-07-10-c (ver docs/HISTORICO_DECISOES.md) com CC, PARA,
# TRANSFERENCIA e ELETRONICO — descrições de transferência entre contas (ex.:
# "TRANSF CC PARA CC ...") traziam "CC"/"PARA" como termos "relevantes" falsos,
# que atrapalhavam (ou coincidentemente ajudavam por acidente) o desempate por nome.
PALAVRAS_GENERICAS_BANCO = {
    "PAGTO", "PAGAMENTO", "ELETRON", "ELETRONICO", "COBRANCA", "TRANSF", "TRANSFERENCIA",
    "PIX", "TED", "DOC", "ENVIADO", "DES", "CC", "PARA",
}
# Ampliada em 2026-07-10-c com DISTRIBUICAO, LUCROS, SALARIO, FOLHA, FERIAS,
# RESCISAO — são marcadores de tipo de lançamento (usados por outras regras a
# partir do texto bruto, nunca desta lista), não identificam QUEM recebeu o
# pagamento; deixá-las como "termo relevante" atrapalhava o desempate por nome
# em grupos de mesmo valor/data (ex.: "Distribuição de Lucros Fulano").
PALAVRAS_GENERICAS_ERP = {
    "REEMBOLSO", "AUXILIO", "CRECHE", "PAGAMENTO", "REMUNERACAO",
    "DISTRIBUICAO", "LUCROS", "SALARIO", "FOLHA", "FERIAS", "RESCISAO",
}
PALAVRAS_GENERICAS_DESCRICAO = PALAVRAS_GENERICAS_BANCO | PALAVRAS_GENERICAS_ERP

# Datas curtas tipo "12/05" ou "5/6" que aparecem no fim de descrições de banco
# (ex.: "PIX ENVIADO DES: FULANO 12/05") e não ajudam a comparar nomes — dentro
# de um grupo de mesmo valor/data elas são sempre iguais entre os candidatos,
# então só atrapalham a comparação por termos relevantes.
PADRAO_DATA_CURTA = re.compile(r"\b\d{1,2}/\d{1,2}\b")

# Período manual de conciliação: se preenchidas, estas constantes têm prioridade
# sobre a detecção automática e filtram tanto o ERP quanto o banco.
DATA_INICIAL_CONCILIACAO = None
DATA_FINAL_CONCILIACAO = None

# Captura "Período: 01/05/2026 à 31/05/2026" (ou variações com "a"/"-") no
# relatório do GestãoClick, já com o texto normalizado (maiúsculo, sem acento).
PADRAO_PERIODO_RELATORIO = re.compile(r"PERIODO.*?(\d{1,2}/\d{1,2}/\d{4}).*?(\d{1,2}/\d{1,2}/\d{4})")

LINHAS_MAX_PROCURA_CABECALHO = 30
PONTOS_MINIMOS_CABECALHO = 2

# Candidatos de nomes de coluna aceitos nas planilhas de origem (ERP ou banco).
# A comparação é feita normalizando o texto (minúsculo, sem acento).
# Ordem importa: o primeiro candidato encontrado é o escolhido.

# Camadas de prioridade para a data do ERP (usadas em src/leitor_erp.py):
# 1) Data de compensação: data real em que o pagamento foi compensado.
# 2) Data de pagamento/baixa/liquidação (ou "Data de confirmação", equivalente
#    em relatórios do GestãoClick): usada quando não há Data de compensação.
# 3) Vencimento: usado apenas como último fallback.
CANDIDATOS_DATA_COMPENSACAO = [
    "data de compensacao",
    "data compensacao",
    "compensacao",
]

CANDIDATOS_DATA_PAGAMENTO = [
    "data de pagamento",
    "data pagamento",
    "data de baixa",
    "data baixa",
    "data de liquidacao",
    "liquidacao",
    "data de confirmacao",
    "data confirmacao",
]

# Usada só para detectar a coluna e preservar "Vencimento Original" para
# auditoria. NUNCA deve ser passada como candidato para `selecionar_data_
# prioritaria` ao montar a Data ERP Usada (regra revisada em 2026-07-10 — ver
# docs/HISTORICO_DECISOES.md): Vencimento é a data prevista de pagamento, não
# a data real, e não pode mais ser usada para conciliar. Ver src/leitor_erp.py.
CANDIDATOS_DATA_VENCIMENTO = [
    "data de vencimento",
    "data vencimento",
    "vencimento",
]

# Usado pelo leitor de banco (planilha com uma única coluna de data): mantém a
# mesma ordem de prioridade das camadas do ERP, mais um fallback genérico "data".
CANDIDATOS_DATA = (
    CANDIDATOS_DATA_COMPENSACAO + CANDIDATOS_DATA_PAGAMENTO + CANDIDATOS_DATA_VENCIMENTO + ["data"]
)

CANDIDATOS_VALOR = [
    "valor",
    "valor pago",
    "valor total",
    "valor (r$)",
    "valor r$",
]

CANDIDATOS_FAVORECIDO = [
    "favorecido",
    "fornecedor",
    "cliente",
    "cliente/fornecedor",
    "descricao",
    "descricao/historico",
    "historico",
    "lancamento",
    "nome",
]

# Coluna de categoria/centro de custo do ERP (usada na regra de lote de salário,
# além do Favorecido, para identificar lançamentos de folha/remuneração).
CANDIDATOS_CATEGORIA = [
    "categoria",
    "centro de custo",
    "centro de custos",
    "categoria financeira",
]

# Termos que, quando encontrados como texto exato de uma célula, indicam que a
# linha é um cabeçalho de tabela (usado para localizar a linha de cabeçalho
# real em relatórios que têm título/período antes da tabela).
TERMOS_CABECALHO = (
    set(CANDIDATOS_DATA) | set(CANDIDATOS_VALOR) | set(CANDIDATOS_FAVORECIDO) | set(CANDIDATOS_CATEGORIA) | {
        "situacao",
        "status",
        "total",
    }
)


def normalizar_texto(texto: str) -> str:
    """Remove acentos e normaliza para minúsculo, para comparação de nomes de coluna."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def normalizar_descricao(texto) -> str:
    """Normaliza uma descrição para comparação: remove acentos, converte para
    maiúsculo, remove datas curtas (ex.: "12/05"), remove pontuação, remove
    espaços extras e descarta palavras genéricas de banco/ERP (PAGTO, PAGAMENTO,
    ELETRON, COBRANCA, TRANSF, PIX, TED, DOC, ENVIADO, DES, REEMBOLSO, AUXILIO,
    CRECHE, REMUNERACAO). O que sobra tende a ser nomes próprios, números de
    documento/provisão e outros termos que realmente identificam o lançamento.
    """
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""

    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    maiusculo = sem_acento.upper()
    sem_data = PADRAO_DATA_CURTA.sub(" ", maiusculo)
    sem_pontuacao = "".join(c if c.isalnum() or c.isspace() else " " for c in sem_data)
    palavras = [p for p in sem_pontuacao.split() if p not in PALAVRAS_GENERICAS_DESCRICAO]
    return " ".join(palavras)


def extrair_termos_relevantes(texto) -> set[str]:
    """Extrai os termos relevantes de uma descrição já normalizada (regra 3):
    tipicamente nomes próprios, números de documento/provisão e outras palavras
    específicas que sobram depois de remover o genérico. Termos com menos de 3
    caracteres são descartados por não serem informativos o suficiente.
    """
    normalizado = normalizar_descricao(texto)
    return {termo for termo in normalizado.split() if len(termo) >= 3}


# Palavras que costumam anteceder um número de documento/nota fiscal e que,
# junto com o número em si, não ajudam a comparar o "fornecedor base" entre
# ERP e banco (o banco normalmente não reproduz o número da NF/documento).
PALAVRAS_MARCADORAS_DOCUMENTO = {"NF", "DOC", "DOCUMENTO", "PC", "PEDIDO", "REF", "NUM", "NUMERO", "NOTA"}


def extrair_termos_base(texto) -> set[str]:
    """Extrai o "fornecedor base" de uma descrição (usado na regra de duplicidade
    equivalente): parte de `normalizar_descricao` e ainda remove números isolados
    (ex.: número de NF/documento) e marcadores de documento, para que
    "PCMSO - Mouro Soluções - NF 200" e "PCMSO - Mouro Soluções - NF 199" cheguem
    ao mesmo conjunto de termos.
    """
    normalizado = normalizar_descricao(texto)
    return {
        termo for termo in normalizado.split()
        if len(termo) >= 3 and not termo.isdigit() and termo not in PALAVRAS_MARCADORAS_DOCUMENTO
    }


def texto_maiusculo_sem_acento(texto) -> str:
    """Converte para maiúsculo e remove acentos, sem descartar nenhuma palavra.

    Usado para detectar palavras-chave literais (ex.: regras de lote de
    salário), diferente de `normalizar_descricao`, que remove palavras
    genéricas de banco e por isso não serve para checar a presença delas.
    """
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.upper().split())


def contem_alguma_palavra(texto, palavras) -> bool:
    """Verifica se o texto contém (como substring, maiúsculo e sem acento) alguma
    das palavras-chave dadas."""
    texto_normalizado = texto_maiusculo_sem_acento(texto)
    return any(palavra in texto_normalizado for palavra in palavras)


def detectar_coluna(colunas, candidatos) -> str | None:
    """Encontra, entre as colunas de um DataFrame, a que corresponde a um dos candidatos."""
    colunas_normalizadas = {normalizar_texto(c): c for c in colunas}
    for candidato in candidatos:
        if candidato in colunas_normalizadas:
            return colunas_normalizadas[candidato]
    return None


def encontrar_arquivo_mais_recente(pasta: Path, extensoes: tuple[str, ...]) -> Path | None:
    """Retorna o arquivo mais recente (por data de modificação) de uma pasta, dentre as extensões dadas."""
    if not pasta.exists():
        return None

    arquivos = [
        arquivo
        for arquivo in pasta.iterdir()
        if (
            arquivo.is_file()
            and arquivo.suffix.lower() in extensoes
            and not arquivo.name.startswith("~$")
            and arquivo.stat().st_size > 0
        )
    ]
    if not arquivos:
        return None

    return max(arquivos, key=lambda arquivo: arquivo.stat().st_mtime)


def arredondar_valor(valor: float) -> float:
    return round(float(valor), 2)


def converter_valor_monetario(valor) -> float | None:
    """Converte um valor de planilha (número ou texto no formato brasileiro) para float.

    Aceita tanto números já convertidos pelo pandas quanto texto como "1.234,56",
    "R$ 1.234,56" ou "(1.234,56)" (negativo entre parênteses).
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None

    if isinstance(valor, (int, float)):
        return round(float(valor), 2)

    texto = str(valor).strip().replace("R$", "").strip()
    if not texto or texto.lower() == "nan":
        return None

    negativo = texto.startswith("(") and texto.endswith(")")
    if negativo:
        texto = texto[1:-1].strip()

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        numero = float(texto)
    except ValueError:
        return None

    return round(-numero if negativo else numero, 2)


def _pontuar_linha_como_cabecalho(valores) -> int:
    """Conta quantas células de uma linha correspondem a um termo típico de cabeçalho."""
    pontos = 0
    for valor in valores:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            continue
        if normalizar_texto(valor) in TERMOS_CABECALHO:
            pontos += 1
    return pontos


def detectar_linha_cabecalho(df_bruto: pd.DataFrame, linhas_max: int = LINHAS_MAX_PROCURA_CABECALHO) -> int | None:
    """Procura, nas primeiras `linhas_max` linhas, qual linha parece ser o cabeçalho real da tabela."""
    limite = min(linhas_max, len(df_bruto))
    melhor_linha, melhor_pontuacao = None, 0

    for indice in range(limite):
        pontuacao = _pontuar_linha_como_cabecalho(df_bruto.iloc[indice])
        if pontuacao > melhor_pontuacao:
            melhor_linha, melhor_pontuacao = indice, pontuacao

    if melhor_pontuacao < PONTOS_MINIMOS_CABECALHO:
        return None

    return melhor_linha


def selecionar_data_prioritaria(indice: pd.Index, candidatos: list[tuple[pd.Series | None, str]]):
    """Escolhe, linha a linha, a primeira data disponível dentre séries em ordem de prioridade.

    `candidatos` é uma lista de tuplas (série de datas ou None, rótulo da origem daquela série).
    Retorna (série de datas escolhidas, série com o rótulo da origem usada em cada linha).
    """
    data_escolhida = pd.Series(pd.NaT, index=indice, dtype="datetime64[ns]")
    origem_escolhida = pd.Series([None] * len(indice), index=indice, dtype="object")

    for serie, rotulo in candidatos:
        if serie is None:
            continue
        preencher = data_escolhida.isna() & serie.notna()
        data_escolhida = data_escolhida.where(~preencher, serie)
        origem_escolhida = origem_escolhida.where(~preencher, rotulo)

    return data_escolhida, origem_escolhida


def _parse_data_br(texto: str):
    """Converte uma data no formato brasileiro (DD/MM/AAAA) para `datetime.date`."""
    try:
        return pd.to_datetime(texto, dayfirst=True).date()
    except (ValueError, TypeError):
        return None


def detectar_periodo_relatorio(df_bruto: pd.DataFrame, linhas_max: int = 5) -> tuple:
    """Procura, nas primeiras linhas do relatório, uma linha "Período: DD/MM/AAAA
    à DD/MM/AAAA" (regras 2 e 3) e retorna (data_inicial, data_final), ou
    (None, None) se não encontrar."""
    limite = min(linhas_max, len(df_bruto))
    for indice in range(limite):
        for valor in df_bruto.iloc[indice]:
            if valor is None or (isinstance(valor, float) and pd.isna(valor)):
                continue
            texto = texto_maiusculo_sem_acento(valor)
            correspondencia = PADRAO_PERIODO_RELATORIO.search(texto)
            if not correspondencia:
                continue
            data_inicial = _parse_data_br(correspondencia.group(1))
            data_final = _parse_data_br(correspondencia.group(2))
            if data_inicial and data_final:
                return data_inicial, data_final
    return None, None


def determinar_periodo_conciliacao(df_bruto: pd.DataFrame, logger: logging.Logger) -> tuple:
    """Regras 9 a 11: usa DATA_INICIAL_CONCILIACAO/DATA_FINAL_CONCILIACAO quando
    preenchidas manualmente; senão tenta identificar o período automaticamente a
    partir da linha "Período: ..." do relatório do GestãoClick. Retorna
    (data_inicial, data_final), com None quando o período não pôde ser definido
    (nesse caso nenhum filtro de período é aplicado)."""
    if DATA_INICIAL_CONCILIACAO is not None and DATA_FINAL_CONCILIACAO is not None:
        logger.info(
            f"Período de conciliação definido manualmente: {DATA_INICIAL_CONCILIACAO} a {DATA_FINAL_CONCILIACAO}"
        )
        return DATA_INICIAL_CONCILIACAO, DATA_FINAL_CONCILIACAO

    data_inicial, data_final = detectar_periodo_relatorio(df_bruto)
    if data_inicial and data_final:
        logger.info(f"Período de conciliação identificado automaticamente no ERP: {data_inicial} a {data_final}")
    else:
        logger.info(
            "Não foi possível identificar o período do relatório do ERP; nenhum filtro de período será aplicado."
        )

    return data_inicial, data_final


def reportar_diagnostico_leitura(
    caminho: Path, nome_aba: str, df_bruto: pd.DataFrame, colunas_encontradas, logger: logging.Logger
) -> None:
    """Loga (console + arquivo) as informações necessárias para o usuário mapear as colunas manualmente."""
    logger.error(f"Diagnóstico de leitura do arquivo '{caminho.name}' (aba: '{nome_aba}'):")
    logger.error("Primeiras 15 linhas da planilha (lida sem cabeçalho):\n%s", df_bruto.head(15).to_string())
    logger.error(f"Colunas encontradas após a tentativa de leitura: {list(colunas_encontradas)}")
    logger.error(
        "Sugestão: identifique manualmente, entre as linhas acima, qual é a linha de cabeçalho e quais colunas "
        "correspondem a Data (ou Data de vencimento), Valor e Favorecido/Descrição. Se os nomes das colunas do "
        "relatório forem muito diferentes dos previstos, ajuste as listas CANDIDATOS_DATA, CANDIDATOS_VALOR e "
        "CANDIDATOS_FAVORECIDO em src/utils.py."
    )


def ler_tabela_com_cabecalho_detectado(caminho: Path, logger: logging.Logger):
    """Localiza a linha de cabeçalho real de um Excel e retorna a tabela a partir dela.

    O relatório pode conter linhas de título/período antes da tabela real (comum em
    exports do GestãoClick): por isso a planilha é lida primeiro sem cabeçalho e a
    linha de cabeçalho real é localizada dentre as primeiras linhas.

    Retorna (df, nome_aba, df_bruto), onde `df` já usa a linha de cabeçalho detectada
    e tem nomes de coluna limpos (sem espaços extras).
    """
    planilha = pd.ExcelFile(caminho)
    nome_aba = planilha.sheet_names[0]
    df_bruto = planilha.parse(nome_aba, header=None)

    linha_cabecalho = detectar_linha_cabecalho(df_bruto)
    if linha_cabecalho is None:
        reportar_diagnostico_leitura(caminho, nome_aba, df_bruto, [], logger)
        raise ValueError(
            f"Não foi possível localizar uma linha de cabeçalho reconhecível nas primeiras "
            f"{LINHAS_MAX_PROCURA_CABECALHO} linhas de '{caminho.name}'. Veja o diagnóstico acima (também "
            f"disponível em logs/) para mapear as colunas manualmente."
        )

    df = planilha.parse(nome_aba, header=linha_cabecalho)
    df.columns = [str(coluna).strip() for coluna in df.columns]

    return df.reset_index(drop=True), nome_aba, df_bruto


def ler_planilha_padrao(caminho: Path, logger: logging.Logger) -> pd.DataFrame:
    """Lê um Excel de ERP ou banco e padroniza para as colunas Data, Valor, Favorecido.

    Não faz suposições sobre o conteúdo: se uma coluna obrigatória não for encontrada,
    lança um erro explícito (com diagnóstico) em vez de adivinhar.
    """
    df, nome_aba, df_bruto = ler_tabela_com_cabecalho_detectado(caminho, logger)

    coluna_data = detectar_coluna(df.columns, CANDIDATOS_DATA)
    coluna_valor = detectar_coluna(df.columns, CANDIDATOS_VALOR)
    coluna_favorecido = detectar_coluna(df.columns, CANDIDATOS_FAVORECIDO)

    if coluna_data is None or coluna_valor is None:
        reportar_diagnostico_leitura(caminho, nome_aba, df_bruto, df.columns, logger)
        raise ValueError(
            f"Não foi possível identificar as colunas de Data e/ou Valor em '{caminho.name}' "
            f"(colunas: {list(df.columns)}). Veja o diagnóstico acima (também disponível em logs/) para mapear "
            f"as colunas manualmente."
        )

    resultado = pd.DataFrame()
    resultado["Data"] = pd.to_datetime(df[coluna_data], dayfirst=True, errors="coerce").dt.date
    resultado["Valor"] = df[coluna_valor].apply(converter_valor_monetario)
    resultado["Favorecido"] = df[coluna_favorecido] if coluna_favorecido else ""

    resultado = resultado.dropna(subset=["Data", "Valor"])
    return resultado.reset_index(drop=True)
