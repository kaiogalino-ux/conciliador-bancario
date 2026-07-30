"""Configuração do logger usado em todo o projeto."""

import logging
import os
from datetime import date
from pathlib import Path

PASTA_LOGS = Path(__file__).resolve().parent.parent / "logs"

VARIAVEL_PASTA_LOGS = "CONCILIADOR_LOG_DIR"


def pasta_logs() -> Path:
    """Pasta onde o log diário é gravado.

    Por padrão é `<backend>/logs`, o mesmo caminho de sempre. Quando o
    projeto roda como serviço HTTP (ver `api/main.py`), o host pode não
    permitir escrita dentro do código — nesse caso a pasta é definida pela
    variável de ambiente `CONCILIADOR_LOG_DIR`.
    """
    configurada = os.environ.get(VARIAVEL_PASTA_LOGS, "").strip()
    return Path(configurada) if configurada else PASTA_LOGS


def obter_logger(nome: str = "conciliador") -> logging.Logger:
    """Cria (ou reaproveita) um logger que grava em console e em arquivo diário.

    Se a pasta de log não puder ser criada ou aberta (disco somente-leitura de
    um servidor, por exemplo), o logger continua funcionando apenas no console
    em vez de interromper a conciliação — o log é auditoria, nunca pode ser o
    motivo de uma execução falhar.
    """
    logger = logging.getLogger(nome)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formato = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(formato)
    logger.addHandler(handler_console)

    destino = pasta_logs()
    try:
        destino.mkdir(parents=True, exist_ok=True)
        arquivo_log = destino / f"conciliador_{date.today():%Y%m%d}.log"
        handler_arquivo = logging.FileHandler(arquivo_log, encoding="utf-8")
        handler_arquivo.setFormatter(formato)
        logger.addHandler(handler_arquivo)
    except OSError as erro:
        logger.warning(
            "Não foi possível gravar o log em '%s' (%s). "
            "A execução continua com log apenas no console.",
            destino,
            erro,
        )

    return logger
