"""Configuração compartilhada dos testes automáticos.

Garante que `import src...` funcione independente de onde o pytest for
chamado, e fornece fixtures/builders para montar DataFrames de ERP e Banco no
mesmo formato que `src/leitor_erp.py` e `src/leitor_banco.py` produzem —
sem precisar de arquivos Excel/OFX reais na maioria dos testes.
"""

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))


@pytest.fixture
def logger_silencioso() -> logging.Logger:
    """Logger que não escreve em `logs/` nem no console — os testes verificam
    o resultado retornado pelas funções, não o texto logado."""
    logger = logging.getLogger("tests.conciliador")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL)
    logger.propagate = False
    return logger


def construir_df_erp(lancamentos: list[dict]) -> pd.DataFrame:
    """Monta um DataFrame de ERP no formato que `conciliar()` espera receber
    (o mesmo que `src/leitor_erp.py` produz). Cada item de `lancamentos` é um
    dict com, no mínimo, `data_usada`, `valor` e `favorecido`; os demais campos
    têm valores padrão razoáveis para não precisar repetir em todo teste.
    """
    linhas = []
    for item in lancamentos:
        linhas.append({
            "Data ERP Usada": item["data_usada"],
            "Tipo Data ERP": item.get("tipo_data", "Data de confirmação"),
            "Valor": float(item["valor"]),
            "Favorecido": item["favorecido"],
            "Categoria": item.get("categoria", ""),
            "Data de Compensação Original": item.get("compensacao_original", pd.NaT),
            "Vencimento Original": item.get("vencimento_original", pd.NaT),
            "Origem": "ERP",
        })
    return pd.DataFrame(linhas)


def construir_df_banco(lancamentos: list[dict]) -> pd.DataFrame:
    """Monta um DataFrame de Banco no formato que `conciliar()` espera receber
    (o mesmo que `src/leitor_banco.py` produz depois do filtro de débitos).
    Cada item é um dict com `data`, `valor` (negativo = débito) e `favorecido`.
    """
    linhas = []
    for item in lancamentos:
        linhas.append({
            "Data": item["data"],
            "Valor": float(item["valor"]),
            "Favorecido": item["favorecido"],
            "Origem": "Banco",
        })
    return pd.DataFrame(linhas)
