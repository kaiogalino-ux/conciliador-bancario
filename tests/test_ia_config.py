"""Protege as regras de configuração da camada de IA (ver CLAUDE.md /
docs/HISTORICO_DECISOES.md): tudo vem de variável de ambiente, nunca de
constante fixa em `src/utils.py`; falta de `GROQ_API_KEY`/`GROQ_MODEL`
nunca derruba `python main.py` (rebaixa para DESATIVADA); e o valor da chave
de API nunca é escrito em nenhuma linha de log.
"""

import logging

import pytest

from src.ia_config import (
    IA_MODO_AUTOMATICO,
    IA_MODO_DESATIVADA,
    IA_MODO_SOMBRA,
    carregar_configuracao_ia,
)

VARIAVEIS_IA = (
    "IA_MODO",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "IA_JANELA_BUSCA_DIAS",
    "IA_JANELA_AUTOMATICA_DIAS",
    "IA_MAXIMO_CANDIDATOS",
    "IA_CONFIANCA_MINIMA_SOMBRA",
    "IA_CONFIANCA_MINIMA_AUTOMATICO",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Garante que cada teste comece sem nenhuma variável de IA definida,
    independente do que estiver no ambiente real de quem roda `pytest`."""
    for nome in VARIAVEIS_IA:
        monkeypatch.delenv(nome, raising=False)


def test_sem_ia_modo_definido_retorna_desativada():
    config = carregar_configuracao_ia()
    assert config.modo == IA_MODO_DESATIVADA
    assert config.api_key is None
    assert config.modelo is None


def test_ia_modo_invalido_retorna_desativada_com_aviso(monkeypatch, caplog):
    monkeypatch.setenv("IA_MODO", "TURBO")
    with caplog.at_level(logging.WARNING):
        config = carregar_configuracao_ia()
    assert config.modo == IA_MODO_DESATIVADA
    assert any("invalido" in r.message.lower() or "inválido" in r.message.lower() for r in caplog.records) or any(
        "TURBO" in r.message for r in caplog.records
    )


def test_ia_modo_sombra_sem_api_key_retorna_desativada(monkeypatch, caplog):
    monkeypatch.setenv("IA_MODO", "SOMBRA")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    with caplog.at_level(logging.WARNING):
        config = carregar_configuracao_ia()
    assert config.modo == IA_MODO_DESATIVADA


def test_ia_modo_sombra_sem_modelo_retorna_desativada(monkeypatch):
    monkeypatch.setenv("IA_MODO", "SOMBRA")
    monkeypatch.setenv("GROQ_API_KEY", "sk-teste-nao-real")
    config = carregar_configuracao_ia()
    assert config.modo == IA_MODO_DESATIVADA


def test_ia_modo_automatico_com_tudo_configurado(monkeypatch):
    monkeypatch.setenv("IA_MODO", "AUTOMATICO")
    monkeypatch.setenv("GROQ_API_KEY", "sk-teste-nao-real")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    config = carregar_configuracao_ia()
    assert config.modo == IA_MODO_AUTOMATICO
    assert config.api_key == "sk-teste-nao-real"
    assert config.modelo == "openai/gpt-oss-120b"


def test_defaults_aplicados_quando_variaveis_opcionais_ausentes(monkeypatch):
    monkeypatch.setenv("IA_MODO", "SOMBRA")
    monkeypatch.setenv("GROQ_API_KEY", "sk-teste")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    config = carregar_configuracao_ia()
    assert config.janela_busca_dias == 5
    assert config.janela_automatica_dias == 1
    assert config.maximo_candidatos == 5
    assert config.confianca_minima_sombra == 0.70
    assert config.confianca_minima_automatico == 0.95


def test_variaveis_opcionais_customizadas_sao_lidas(monkeypatch):
    monkeypatch.setenv("IA_MODO", "AUTOMATICO")
    monkeypatch.setenv("GROQ_API_KEY", "sk-teste")
    monkeypatch.setenv("GROQ_MODEL", "outro-modelo-groq-qualquer")
    monkeypatch.setenv("IA_JANELA_BUSCA_DIAS", "10")
    monkeypatch.setenv("IA_JANELA_AUTOMATICA_DIAS", "2")
    monkeypatch.setenv("IA_MAXIMO_CANDIDATOS", "3")
    monkeypatch.setenv("IA_CONFIANCA_MINIMA_SOMBRA", "0.6")
    monkeypatch.setenv("IA_CONFIANCA_MINIMA_AUTOMATICO", "0.99")

    config = carregar_configuracao_ia()

    assert config.janela_busca_dias == 10
    assert config.janela_automatica_dias == 2
    assert config.maximo_candidatos == 3
    assert config.confianca_minima_sombra == 0.6
    assert config.confianca_minima_automatico == 0.99


def test_chave_api_nunca_aparece_em_nenhuma_mensagem_de_log(monkeypatch, caplog):
    chave_secreta = "gsk-super-secreta-nao-pode-vazar"
    monkeypatch.setenv("IA_MODO", "SOMBRA")
    monkeypatch.setenv("GROQ_API_KEY", chave_secreta)
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")

    with caplog.at_level(logging.DEBUG):
        carregar_configuracao_ia()

    for registro in caplog.records:
        assert chave_secreta not in registro.message

    # Também sem chave/modelo, garantindo que o aviso de fallback também
    # nunca ecoa nada sensível (aqui não há chave nenhuma, mas o teste cobre
    # o outro caminho de log).
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with caplog.at_level(logging.DEBUG):
        carregar_configuracao_ia()
    for registro in caplog.records:
        assert chave_secreta not in registro.message
