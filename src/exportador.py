"""Geração do arquivo resultado/Resultado.xlsx.

Regra 2 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): o arquivo tem uma
única aba, "Resultado". Todo o diagnóstico que antes vivia em abas separadas
(Revisão Manual, Lotes NET EMP, Não Encontrados) já vem embutido como colunas
em cada linha (Motivo Revisão, Motivo Não Conciliado, Possível Data/Valor/
Descrição Banco, Status do Possível Banco) — ver src/conciliador.py.
"""

import logging
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font

NOME_ABA_RESULTADO = "Resultado"


def exportar_resultado(resultado: pd.DataFrame, caminho_saida: Path, logger: logging.Logger) -> None:
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        resultado.to_excel(writer, index=False, sheet_name=NOME_ABA_RESULTADO)

    _formatar_planilha(caminho_saida, NOME_ABA_RESULTADO)

    logger.info(f"Resultado exportado para: {caminho_saida}")
    logger.info(f"Aba única '{NOME_ABA_RESULTADO}': {len(resultado)} linha(s).")


def _formatar_planilha(caminho: Path, nome_aba: str) -> None:
    from openpyxl import load_workbook

    workbook = load_workbook(caminho)
    planilha = workbook[nome_aba]

    for celula in planilha[1]:
        celula.font = Font(bold=True)

    for coluna in planilha.columns:
        maior_largura = max(len(str(celula.value)) if celula.value is not None else 0 for celula in coluna)
        letra_coluna = coluna[0].column_letter
        planilha.column_dimensions[letra_coluna].width = min(maior_largura + 2, 60)

    planilha.freeze_panes = "A2"
    workbook.save(caminho)
