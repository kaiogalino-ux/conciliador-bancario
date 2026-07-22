"""Configuração do logger usado em todo o projeto."""

import logging
from datetime import date
from pathlib import Path

PASTA_LOGS = Path(__file__).resolve().parent.parent / "logs"


def obter_logger(nome: str = "conciliador") -> logging.Logger:
    """Cria (ou reaproveita) um logger que grava em console e em arquivo diário."""
    logger = logging.getLogger(nome)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formato = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo_log = PASTA_LOGS / f"conciliador_{date.today():%Y%m%d}.log"

    handler_arquivo = logging.FileHandler(arquivo_log, encoding="utf-8")
    handler_arquivo.setFormatter(formato)

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(formato)

    logger.addHandler(handler_arquivo)
    logger.addHandler(handler_console)

    return logger
