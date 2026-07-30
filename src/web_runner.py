"""Adaptador local entre a interface web e o pipeline de conciliação.

Este módulo não contém regras novas de conciliação. Ele apenas executa os
mesmos leitores, conciliador e exportador usados por ``main.py`` e transforma
o resumo final em JSON para a interface local.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.conciliador import (
    STATUS_NAO_ENCONTRADO_BANCO,
    conciliar,
)
from src.exportador import (
    _calcular_metricas_financeiras,
    _calcular_metricas_status,
    _montar_linhas_pendentes,
    exportar_resultado,
)
from src.ia_config import carregar_configuracao_ia
from src.leitor_banco import ler_banco
from src.leitor_erp import ler_erp
from src.logger import obter_logger

LIMITE_PREVIA_PENDENTES = 500


def _valor_json(valor: Any) -> Any:
    """Converte datas e escalares do pandas/numpy para JSON válido."""
    if valor is None:
        return None
    if isinstance(valor, (pd.Timestamp, datetime, date)):
        return valor.isoformat()
    if hasattr(valor, "item"):
        try:
            valor = valor.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor


def _serializar_pendencia(item: dict) -> dict:
    return {
        "data": _valor_json(item.get("Data")),
        "origem": _valor_json(item.get("Origem")) or "",
        "favorecido": _valor_json(item.get("Favorecido ou descrição")) or "",
        "valorGestao": _valor_json(item.get("Valor na Gestão")),
        "valorBanco": _valor_json(item.get("Valor no banco")),
        "status": _valor_json(item.get("Status")) or "",
        "motivo": _valor_json(item.get("Motivo")) or "",
    }


def montar_resposta_web(
    resultado: pd.DataFrame,
    *,
    periodo_inicial=None,
    periodo_final=None,
    total_linhas_erp: int,
    total_linhas_banco: int,
) -> dict:
    """Monta o contrato de resposta da interface sem alterar ``resultado``."""
    metricas_financeiras = _calcular_metricas_financeiras(resultado)
    metricas_status = _calcular_metricas_status(resultado)
    pendentes = _montar_linhas_pendentes(resultado)

    total = metricas_status["total"]
    qtd_nao_encontrado = (
        int((resultado["Status"] == STATUS_NAO_ENCONTRADO_BANCO).sum())
        if total and "Status" in resultado.columns
        else 0
    )

    def indicador(chave: str) -> dict:
        quantidade, percentual = metricas_status[chave]
        return {
            "quantidade": int(quantidade),
            "percentual": round(float(percentual) * 100, 1),
        }

    return {
        "periodo": {
            "inicio": _valor_json(periodo_inicial),
            "fim": _valor_json(periodo_final),
        },
        "entradas": {
            "linhasGestao": int(total_linhas_erp),
            "linhasBanco": int(total_linhas_banco),
        },
        "indicadores": {
            "totalGestao": metricas_financeiras["total_erp"],
            "totalBanco": metricas_financeiras["total_banco"],
            "conciliado": indicador("conciliados"),
            "revisaoManual": indicador("revisao"),
            "somenteBanco": indicador("somente_banco"),
            "naoEncontradoBanco": {
                "quantidade": qtd_nao_encontrado,
                "percentual": round((qtd_nao_encontrado / total * 100) if total else 0.0, 1),
            },
            "totalLinhas": int(total),
        },
        "pendentes": [
            _serializar_pendencia(item)
            for item in pendentes[:LIMITE_PREVIA_PENDENTES]
        ],
        "pendentesTotal": len(pendentes),
        "pendentesExibidos": min(len(pendentes), LIMITE_PREVIA_PENDENTES),
    }


def executar_conciliacao_web(
    pasta_erp: Path,
    pasta_banco: Path,
    caminho_resultado: Path,
) -> dict:
    """Executa o fluxo oficial e retorna somente dados de apresentação."""
    logger = obter_logger("conciliador_web")
    logger.info("Iniciando conciliação solicitada pela interface local.")

    df_erp, periodo_inicial, periodo_final = ler_erp(pasta_erp, logger)
    df_banco = ler_banco(
        pasta_banco,
        logger,
        periodo_inicial,
        periodo_final,
    )
    config_ia = carregar_configuracao_ia(logger)
    resultado = conciliar(df_erp, df_banco, logger, config_ia=config_ia)
    exportar_resultado(
        resultado,
        caminho_resultado,
        logger,
        periodo_inicial=periodo_inicial,
        periodo_final=periodo_final,
    )

    resposta = montar_resposta_web(
        resultado,
        periodo_inicial=periodo_inicial,
        periodo_final=periodo_final,
        total_linhas_erp=len(df_erp),
        total_linhas_banco=len(df_banco),
    )
    resposta["arquivoResultado"] = caminho_resultado.name
    logger.info("Conciliação da interface local concluída com sucesso.")
    return resposta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Executa a conciliação para a interface web local."
    )
    parser.add_argument("--erp-dir", required=True, type=Path)
    parser.add_argument("--banco-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    argumentos = parser.parse_args()

    resposta = executar_conciliacao_web(
        argumentos.erp_dir.resolve(),
        argumentos.banco_dir.resolve(),
        argumentos.output.resolve(),
    )
    print(json.dumps(resposta, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
