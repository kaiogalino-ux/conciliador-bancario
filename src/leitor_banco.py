"""Leitura do extrato bancário (OFX ou Excel)."""

import logging
from io import StringIO
from pathlib import Path

import pandas as pd
from ofxparse import OfxParser

from src.utils import EXTENSOES_EXCEL, encontrar_arquivo_mais_recente, arredondar_valor, ler_planilha_padrao

EXTENSOES_BANCO = (".ofx",) + EXTENSOES_EXCEL

# Ordem de tentativa de codificação ao ler o OFX: bancos brasileiros costumam
# exportar em Latin-1/CP1252/ISO-8859-1, mas alguns já usam UTF-8.
ENCODINGS_OFX = ["utf-8-sig", "utf-8", "cp1252", "latin-1", "iso-8859-1"]


def ler_banco(
    pasta_banco: Path, logger: logging.Logger, periodo_inicial=None, periodo_final=None
) -> pd.DataFrame:
    """Localiza o extrato mais recente (OFX ou Excel) em `dados/Banco` e retorna o DataFrame padronizado.

    Se `periodo_inicial`/`periodo_final` forem informados (regras 4 a 8), lançamentos
    com Data fora desse período são ignorados e não entram na conciliação.
    """
    arquivo = encontrar_arquivo_mais_recente(pasta_banco, EXTENSOES_BANCO)
    if arquivo is None:
        raise FileNotFoundError(f"Nenhum arquivo OFX ou Excel encontrado em '{pasta_banco}'.")

    logger.info(f"Lendo arquivo do banco: {arquivo.name}")

    if arquivo.suffix.lower() == ".ofx":
        df = _ler_ofx(arquivo, logger)
    else:
        df = ler_planilha_padrao(arquivo, logger)

    df["Origem"] = "Banco"

    total_lido = len(df)
    df = df[df["Valor"] < 0].reset_index(drop=True)
    qtd_debitos = len(df)
    qtd_creditos_ignorados = total_lido - qtd_debitos

    logger.info(f"Total de lançamentos lidos no banco: {total_lido}")
    logger.info(f"Débitos/saídas considerados: {qtd_debitos}")
    logger.info(f"Créditos/entradas ignorados: {qtd_creditos_ignorados}")

    if periodo_inicial and periodo_final:
        df = _filtrar_por_periodo(df, periodo_inicial, periodo_final, logger)

    return df


def _filtrar_por_periodo(df: pd.DataFrame, periodo_inicial, periodo_final, logger: logging.Logger) -> pd.DataFrame:
    """Regras 5 a 8: mantém só lançamentos com Data dentro do período de conciliação,
    registrando no log (data, valor, descrição e motivo) cada um que for descartado."""
    antes_do_filtro = len(df)
    dentro_do_periodo = (df["Data"] >= periodo_inicial) & (df["Data"] <= periodo_final)

    for _, linha in df.loc[~dentro_do_periodo].iterrows():
        logger.info(
            f"Ignorado fora do período da conciliação: Data={linha['Data']}, Valor={linha['Valor']}, "
            f"Descrição='{linha['Favorecido']}', Motivo='Fora do período da conciliação'"
        )

    df = df.loc[dentro_do_periodo].reset_index(drop=True)
    depois_do_filtro = len(df)

    logger.info(f"Lançamentos do banco antes do filtro de período: {antes_do_filtro}")
    logger.info(f"Lançamentos do banco depois do filtro de período: {depois_do_filtro}")
    logger.info(f"Lançamentos do banco ignorados por estarem fora do período: {antes_do_filtro - depois_do_filtro}")

    return df


def _abrir_ofx_com_encoding(caminho: Path):
    """Lê o conteúdo do OFX como texto, testando as codificações em ENCODINGS_OFX
    nesta ordem (a primeira que não gerar UnicodeDecodeError é usada). O arquivo
    original nunca é alterado — só é aberto para leitura e repassado ao OfxParser
    via StringIO. Retorna (ofx, encoding_usado)."""
    ultimo_erro = None

    for encoding in ENCODINGS_OFX:
        try:
            with open(caminho, "r", encoding=encoding) as arquivo:
                conteudo = arquivo.read()

            # Alguns bancos exportam o OFX com uma linha em branco antes de
            # "OFXHEADER:100". O parser da ofxparse lê o cabeçalho linha a linha e
            # trata a primeira linha em branco como fim do cabeçalho — se ela vier
            # antes do cabeçalho de verdade, o ENCODING/CHARSET declarados no
            # arquivo são ignorados e a biblioteca cai num decode ascii que quebra
            # com acentos. Remover espaços/linhas em branco do início do texto (só
            # na cópia em memória usada para o parser) evita esse problema.
            conteudo = conteudo.lstrip()

            ofx = OfxParser.parse(StringIO(conteudo))
            return ofx, encoding
        except UnicodeDecodeError as erro:
            ultimo_erro = erro
            continue

    raise UnicodeDecodeError(
        "ofx", b"", 0, 1,
        f"Não foi possível ler o OFX com as codificações testadas ({', '.join(ENCODINGS_OFX)}). "
        f"Último erro: {ultimo_erro}"
    )


def _ler_ofx(caminho: Path, logger: logging.Logger) -> pd.DataFrame:
    ofx, encoding = _abrir_ofx_com_encoding(caminho)
    logger.info(f"Arquivo OFX lido com encoding: {encoding}")

    contas = getattr(ofx, "accounts", None) or [ofx.account]

    linhas = []
    for conta in contas:
        for transacao in conta.statement.transactions:
            linhas.append(
                {
                    "Data": transacao.date.date(),
                    "Valor": arredondar_valor(transacao.amount),
                    "Favorecido": transacao.payee or transacao.memo or "",
                }
            )

    return pd.DataFrame(linhas, columns=["Data", "Valor", "Favorecido"])
