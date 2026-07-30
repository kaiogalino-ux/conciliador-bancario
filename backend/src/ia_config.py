"""Configuração da camada de IA (2ª etapa decisiva de conciliação).

Toda configuração vem exclusivamente de variáveis de ambiente (`.env`, via
`python-dotenv`, ou variáveis já definidas no ambiente real) — nunca de
constantes em `src/utils.py`. Ver `.env.example` para a lista completa e
`CLAUDE.md`/`docs/HISTORICO_DECISOES.md` para o motivo dessa decisão.

O valor de `GROQ_API_KEY` nunca é escrito em nenhuma linha de log, em nenhum
nível — só a informação booleana de que está (ou não) configurada.
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Carrega variáveis de um arquivo .env na raiz do projeto, se existir. Nunca
# sobrescreve uma variável já definida no ambiente real (comportamento padrão
# de load_dotenv). Chamado uma única vez, na importação do módulo.
load_dotenv()

IA_MODO_DESATIVADA = "DESATIVADA"
IA_MODO_SOMBRA = "SOMBRA"
IA_MODO_AUTOMATICO = "AUTOMATICO"
MODOS_VALIDOS = (IA_MODO_DESATIVADA, IA_MODO_SOMBRA, IA_MODO_AUTOMATICO)

_DEFAULT_JANELA_BUSCA_DIAS = 0
_DEFAULT_JANELA_AUTOMATICA_DIAS = 0
_DEFAULT_MAXIMO_CANDIDATOS = 5
_DEFAULT_CONFIANCA_MINIMA_SOMBRA = 0.70
_DEFAULT_CONFIANCA_MINIMA_AUTOMATICO = 0.95


@dataclass(frozen=True)
class ConfiguracaoIA:
    modo: str
    api_key: str | None
    modelo: str | None
    janela_busca_dias: int
    janela_automatica_dias: int
    maximo_candidatos: int
    confianca_minima_sombra: float
    confianca_minima_automatico: float

    @staticmethod
    def desativada() -> "ConfiguracaoIA":
        return ConfiguracaoIA(
            modo=IA_MODO_DESATIVADA,
            api_key=None,
            modelo=None,
            janela_busca_dias=_DEFAULT_JANELA_BUSCA_DIAS,
            janela_automatica_dias=_DEFAULT_JANELA_AUTOMATICA_DIAS,
            maximo_candidatos=_DEFAULT_MAXIMO_CANDIDATOS,
            confianca_minima_sombra=_DEFAULT_CONFIANCA_MINIMA_SOMBRA,
            confianca_minima_automatico=_DEFAULT_CONFIANCA_MINIMA_AUTOMATICO,
        )


def _ler_int(
    nome: str,
    default: int,
    logger: logging.Logger,
    minimo: int,
    maximo: int,
) -> int:
    valor = os.environ.get(nome)
    if valor is None or not valor.strip():
        return default
    try:
        numero = int(valor.strip())
    except ValueError:
        logger.warning(f"{nome} inválido; usando o padrão {default}.")
        return default
    if not minimo <= numero <= maximo:
        logger.warning(
            f"{nome} fora do intervalo permitido ({minimo} a {maximo}); "
            f"usando o padrão {default}."
        )
        return default
    return numero


def _ler_float(
    nome: str,
    default: float,
    logger: logging.Logger,
    minimo: float,
    maximo: float,
) -> float:
    valor = os.environ.get(nome)
    if valor is None or not valor.strip():
        return default
    try:
        numero = float(valor.strip())
    except ValueError:
        logger.warning(f"{nome} inválido; usando o padrão {default}.")
        return default
    if not minimo <= numero <= maximo:
        logger.warning(
            f"{nome} fora do intervalo permitido ({minimo} a {maximo}); "
            f"usando o padrão {default}."
        )
        return default
    return numero


def carregar_configuracao_ia(logger: logging.Logger | None = None) -> ConfiguracaoIA:
    """Lê `IA_MODO` e as demais variáveis de ambiente da camada de IA.

    Se `IA_MODO` pedir `SOMBRA`/`AUTOMATICO` mas `GROQ_API_KEY` ou
    `GROQ_MODEL` estiverem ausentes (ou `IA_MODO` tiver um valor
    desconhecido), rebaixa para `ConfiguracaoIA.desativada()` com um aviso no
    log — a ausência de configuração nunca derruba `python main.py`.
    """
    logger = logger or logging.getLogger("conciliador")

    modo_bruto = os.environ.get("IA_MODO", IA_MODO_DESATIVADA).strip().upper()
    modo = modo_bruto or IA_MODO_DESATIVADA

    if modo not in MODOS_VALIDOS:
        logger.warning(
            f"IA_MODO='{modo_bruto}' inválido (esperado um de {MODOS_VALIDOS}); "
            "camada de IA desativada nesta execução."
        )
        return ConfiguracaoIA.desativada()

    if modo == IA_MODO_DESATIVADA:
        return ConfiguracaoIA.desativada()

    api_key = os.environ.get("GROQ_API_KEY") or None
    modelo = os.environ.get("GROQ_MODEL") or None
    logger.info(f"IA_MODO='{modo}' pedido. GROQ_API_KEY configurada: {'sim' if api_key else 'não'}.")
    logger.info(f"GROQ_MODEL configurado: {modelo if modelo else 'não'}.")

    if not api_key or not modelo:
        logger.warning(
            f"IA_MODO='{modo}' pedido, mas GROQ_API_KEY e/ou GROQ_MODEL não estão configurados "
            "— camada de IA desativada nesta execução (a conciliação determinística continua normalmente)."
        )
        return ConfiguracaoIA.desativada()

    janela_busca_dias = _ler_int(
        "IA_JANELA_BUSCA_DIAS", _DEFAULT_JANELA_BUSCA_DIAS, logger, 0, 0
    )
    janela_automatica_dias = _ler_int(
        "IA_JANELA_AUTOMATICA_DIAS", _DEFAULT_JANELA_AUTOMATICA_DIAS, logger, 0, 0
    )
    maximo_candidatos = _ler_int(
        "IA_MAXIMO_CANDIDATOS", _DEFAULT_MAXIMO_CANDIDATOS, logger, 1, 5
    )
    confianca_minima_sombra = _ler_float(
        "IA_CONFIANCA_MINIMA_SOMBRA", _DEFAULT_CONFIANCA_MINIMA_SOMBRA, logger, 0.0, 1.0
    )
    confianca_minima_automatico = _ler_float(
        "IA_CONFIANCA_MINIMA_AUTOMATICO", _DEFAULT_CONFIANCA_MINIMA_AUTOMATICO, logger, 0.0, 1.0
    )
    if confianca_minima_automatico < confianca_minima_sombra:
        logger.warning(
            "IA_CONFIANCA_MINIMA_AUTOMATICO não pode ser menor que "
            "IA_CONFIANCA_MINIMA_SOMBRA; usando o padrão automático "
            f"{_DEFAULT_CONFIANCA_MINIMA_AUTOMATICO}."
        )
        confianca_minima_automatico = _DEFAULT_CONFIANCA_MINIMA_AUTOMATICO

    return ConfiguracaoIA(
        modo=modo,
        api_key=api_key,
        modelo=modelo,
        janela_busca_dias=janela_busca_dias,
        janela_automatica_dias=janela_automatica_dias,
        maximo_candidatos=maximo_candidatos,
        confianca_minima_sombra=confianca_minima_sombra,
        confianca_minima_automatico=confianca_minima_automatico,
    )
