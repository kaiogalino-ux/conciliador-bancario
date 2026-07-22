"""Leitura do Excel exportado do GestãoClick.

Prioridade da data usada na conciliação (a "Data ERP Usada"):
1. Data de compensação — data real em que o pagamento foi compensado.
2. Data de pagamento/baixa/liquidação (ou "Data de confirmação", equivalente
   em relatórios do GestãoClick) — usada linha a linha quando não há Data de
   compensação preenchida.

Vencimento NUNCA é usado como Data ERP Usada (regra revisada em 2026-07-10 —
ver docs/HISTORICO_DECISOES.md; antes era o 3º fallback). Uma linha sem
nenhuma data de pagamento/compensação/confirmação real fica com Data ERP
Usada vazia (NaT) e é preservada aqui (não descartada) — `src/conciliador.py`
a marca como Revisão Manual com um motivo específico, em vez de tentar casar
com o banco usando o vencimento. A coluna "Vencimento Original" continua
sendo lida e preservada só para auditoria.
"""

import logging
from pathlib import Path

import pandas as pd

from src.utils import (
    CANDIDATOS_CATEGORIA,
    CANDIDATOS_DATA_COMPENSACAO,
    CANDIDATOS_DATA_PAGAMENTO,
    CANDIDATOS_DATA_VENCIMENTO,
    CANDIDATOS_FAVORECIDO,
    CANDIDATOS_VALOR,
    EXTENSOES_EXCEL,
    converter_valor_monetario,
    detectar_coluna,
    determinar_periodo_conciliacao,
    encontrar_arquivo_mais_recente,
    ler_tabela_com_cabecalho_detectado,
    reportar_diagnostico_leitura,
    selecionar_data_prioritaria,
)

ROTULO_COMPENSACAO = "Data de compensação"
ROTULO_VENCIMENTO = "Vencimento"


def ler_erp(pasta_erp: Path, logger: logging.Logger) -> tuple:
    """Localiza o Excel mais recente em `dados/ERP` e retorna (DataFrame padronizado,
    data_inicial, data_final) — o período de conciliação identificado (regras 1 a 11),
    usado depois para filtrar também o banco."""
    arquivo = encontrar_arquivo_mais_recente(pasta_erp, EXTENSOES_EXCEL)
    if arquivo is None:
        raise FileNotFoundError(f"Nenhum arquivo Excel encontrado em '{pasta_erp}'.")

    logger.info(f"Lendo arquivo do ERP: {arquivo.name}")
    df, nome_aba, df_bruto = ler_tabela_com_cabecalho_detectado(arquivo, logger)

    periodo_inicial, periodo_final = determinar_periodo_conciliacao(df_bruto, logger)

    logger.info(f"Colunas encontradas no ERP: {list(df.columns)}")

    coluna_compensacao = detectar_coluna(df.columns, CANDIDATOS_DATA_COMPENSACAO)
    coluna_pagamento = detectar_coluna(df.columns, CANDIDATOS_DATA_PAGAMENTO)
    coluna_vencimento = detectar_coluna(df.columns, CANDIDATOS_DATA_VENCIMENTO)
    coluna_valor = detectar_coluna(df.columns, CANDIDATOS_VALOR)
    coluna_favorecido = detectar_coluna(df.columns, CANDIDATOS_FAVORECIDO)
    coluna_categoria = detectar_coluna(df.columns, CANDIDATOS_CATEGORIA)

    if coluna_valor is None:
        reportar_diagnostico_leitura(arquivo, nome_aba, df_bruto, df.columns, logger)
        raise ValueError(
            f"Não foi possível identificar a coluna de Valor em '{arquivo.name}' (colunas: {list(df.columns)}). "
            f"Veja o diagnóstico acima (também disponível em logs/) para mapear as colunas manualmente."
        )

    if coluna_compensacao is None and coluna_pagamento is None and coluna_vencimento is None:
        reportar_diagnostico_leitura(arquivo, nome_aba, df_bruto, df.columns, logger)
        raise ValueError(
            f"Não foi possível identificar nenhuma coluna de data (Data de compensação, Data de "
            f"pagamento/baixa/liquidação ou Vencimento) em '{arquivo.name}' (colunas: {list(df.columns)}). "
            f"Veja o diagnóstico acima (também disponível em logs/) para mapear as colunas manualmente."
        )

    coluna_data_erp_escolhida = coluna_compensacao or coluna_pagamento or coluna_vencimento
    logger.info(f"Coluna escolhida como Data ERP (principal): '{coluna_data_erp_escolhida}'")
    logger.info(f"Coluna escolhida como Valor ERP: '{coluna_valor}'")
    logger.info(f"Coluna escolhida como Favorecido: '{coluna_favorecido or '(não encontrada)'}'")
    logger.info(
        f"Coluna 'Data de compensação' encontrada no relatório do ERP: "
        f"{'Sim (' + coluna_compensacao + ')' if coluna_compensacao else 'Não'}"
    )

    data_compensacao = (
        pd.to_datetime(df[coluna_compensacao], dayfirst=True, errors="coerce") if coluna_compensacao else None
    )
    data_pagamento = (
        pd.to_datetime(df[coluna_pagamento], dayfirst=True, errors="coerce") if coluna_pagamento else None
    )
    data_vencimento = (
        pd.to_datetime(df[coluna_vencimento], dayfirst=True, errors="coerce") if coluna_vencimento else None
    )

    if data_compensacao is not None:
        qtd_com_compensacao = int(data_compensacao.notna().sum())
        qtd_sem_compensacao = int(data_compensacao.isna().sum())
    else:
        qtd_com_compensacao = 0
        qtd_sem_compensacao = len(df)

    logger.info(f"Linhas com Data de compensação preenchida: {qtd_com_compensacao}")
    logger.info(f"Linhas sem Data de compensação preenchida: {qtd_sem_compensacao}")

    # Vencimento nunca entra nesta lista (regra de 2026-07-10) — só datas que
    # representam pagamento/compensação real podem virar Data ERP Usada.
    data_erp_usada, tipo_data_erp = selecionar_data_prioritaria(
        df.index,
        [
            (data_compensacao, ROTULO_COMPENSACAO),
            (data_pagamento, coluna_pagamento),
        ],
    )

    resultado = pd.DataFrame(index=df.index)
    resultado["Data ERP Usada"] = data_erp_usada
    resultado["Tipo Data ERP"] = tipo_data_erp
    resultado["Valor"] = df[coluna_valor].apply(converter_valor_monetario)
    resultado["Favorecido"] = df[coluna_favorecido] if coluna_favorecido else ""
    resultado["Categoria"] = df[coluna_categoria] if coluna_categoria else ""
    # Colunas de auditoria: guardam a data original de cada coluna, mesmo quando
    # ela não é a "Data ERP Usada" — permitem conferir, linha a linha, que a
    # prioridade (Data de compensação > pagamento/confirmação > Vencimento) foi
    # respeitada, e servem de sinal extra no desempate por descrição (ex.:
    # distinguir "Licenciamento 2022" de "2023" pelo ano do Vencimento).
    resultado["Data de Compensação Original"] = (
        data_compensacao if data_compensacao is not None else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    )
    resultado["Vencimento Original"] = (
        data_vencimento if data_vencimento is not None else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    )
    resultado["Origem"] = "ERP"

    # Só o Valor é obrigatório para manter a linha — uma linha sem nenhuma data
    # de pagamento/compensação (só vencimento, ou nenhuma data) é PRESERVADA
    # aqui (não descartada): vira Revisão Manual em src/conciliador.py, com
    # motivo explícito, em vez de desaparecer silenciosamente do resultado.
    resultado = resultado.dropna(subset=["Valor"])
    resultado["Data ERP Usada"] = resultado["Data ERP Usada"].dt.date
    resultado["Data de Compensação Original"] = resultado["Data de Compensação Original"].dt.date
    resultado["Vencimento Original"] = resultado["Vencimento Original"].dt.date

    contagem_tipo_data = resultado["Tipo Data ERP"].value_counts().to_dict()
    qtd_sem_data_pagamento = int(resultado["Data ERP Usada"].isna().sum())
    logger.info(f"Linhas que usaram 'Data de compensação' como Data ERP Usada: {contagem_tipo_data.get(ROTULO_COMPENSACAO, 0)}")
    logger.info(
        f"Linhas sem nenhuma data de pagamento/compensação (só vencimento, ou nenhuma data — "
        f"vencimento nunca é usado para conciliação): {qtd_sem_data_pagamento}"
    )
    if coluna_pagamento:
        logger.info(
            f"Linhas que usaram '{coluna_pagamento}' como fallback intermediário: {contagem_tipo_data.get(coluna_pagamento, 0)}"
        )

    if periodo_inicial and periodo_final:
        antes = len(resultado)
        dentro_do_periodo = resultado["Data ERP Usada"].isna() | (
            (resultado["Data ERP Usada"] >= periodo_inicial) & (resultado["Data ERP Usada"] <= periodo_final)
        )
        resultado = resultado[dentro_do_periodo]
        ignorados = antes - len(resultado)
        if ignorados:
            logger.info(f"Lançamentos do ERP fora do período da conciliação (ignorados): {ignorados}")

    logger.info(f"{len(resultado)} lançamento(s) lido(s) do ERP.")
    return resultado.reset_index(drop=True), periodo_inicial, periodo_final
