"""Testa src/ia_cliente_groq.py com um SDK 'groq' falso injetado em
sys.modules — nunca faz nenhuma chamada de rede real. Cobre: decodificação
correta do JSON de `choices[0].message.content`, erro quando não há
`choices`, erro quando o conteúdo vem vazio/recusado, erro quando o conteúdo
não é JSON válido, erro quando o SDK lança exceção (rede/timeout/rate limit —
captura ampla, uma família só), erro quando o pacote não está instalado, e
que `modelo`/`api_key` usados na chamada são sempre os recebidos por
parâmetro (nunca fixos no código — requisito explícito do usuário), com
`response_format` sempre em Structured Outputs `strict=true`.
"""

import json
import sys
import types

import pytest

from src.ia_cliente_groq import ErroConsultaIA, consultar

LABELS = ["C1", "C2", "C3"]


class _Mensagem:
    def __init__(self, content):
        self.content = content


class _Escolha:
    def __init__(self, content):
        self.message = _Mensagem(content)


class _RespostaFalsa:
    def __init__(self, escolhas):
        self.choices = escolhas


def _instalar_groq_falso(monkeypatch, comportamento_create, capturar_chamadas: dict):
    """Registra em sys.modules um módulo 'groq' falso cujo
    Groq().chat.completions.create(**kwargs) delega para `comportamento_create`."""

    class _CompletionsFalso:
        def create(self, **kwargs):
            capturar_chamadas["kwargs"] = kwargs
            return comportamento_create(**kwargs)

    class _ChatFalso:
        def __init__(self):
            self.completions = _CompletionsFalso()

    class _GroqFalso:
        def __init__(self, api_key=None):
            capturar_chamadas["api_key"] = api_key
            self.chat = _ChatFalso()

    modulo_falso = types.ModuleType("groq")
    modulo_falso.Groq = _GroqFalso
    monkeypatch.setitem(sys.modules, "groq", modulo_falso)


def test_consultar_retorna_json_decodificado_do_conteudo(monkeypatch):
    capturado = {}
    decisao_esperada = {"decisao": "CONCILIAR", "candidato": "C2", "confianca": 0.97, "motivo": "Nome bate."}

    _instalar_groq_falso(
        monkeypatch,
        lambda **kwargs: _RespostaFalsa([_Escolha(json.dumps(decisao_esperada))]),
        capturado,
    )

    resultado = consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")

    assert resultado == decisao_esperada


def test_consultar_usa_modelo_e_api_key_recebidos_por_parametro(monkeypatch):
    capturado = {}
    _instalar_groq_falso(
        monkeypatch,
        lambda **kwargs: _RespostaFalsa(
            [_Escolha(json.dumps({"decisao": "NENHUM_CANDIDATO", "candidato": None, "confianca": 0.1, "motivo": "x"}))]
        ),
        capturado,
    )

    consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-outra-chave")

    assert capturado["kwargs"]["model"] == "openai/gpt-oss-120b"
    assert capturado["api_key"] == "gsk-outra-chave"


def test_consultar_usa_structured_outputs_strict_com_schema_correto(monkeypatch):
    capturado = {}
    _instalar_groq_falso(
        monkeypatch,
        lambda **kwargs: _RespostaFalsa(
            [_Escolha(json.dumps({"decisao": "NENHUM_CANDIDATO", "candidato": None, "confianca": 0.1, "motivo": "x"}))]
        ),
        capturado,
    )

    consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")

    response_format = capturado["kwargs"]["response_format"]
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["strict"] is True
    schema = json_schema["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"decisao", "candidato", "confianca", "motivo"}
    assert schema["properties"]["candidato"]["enum"] == ["C1", "C2", "C3", "C4", "C5", None]


def test_consultar_sem_choices_lanca_erro_consulta_ia(monkeypatch):
    capturado = {}
    _instalar_groq_falso(monkeypatch, lambda **kwargs: _RespostaFalsa([]), capturado)

    with pytest.raises(ErroConsultaIA):
        consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")


def test_consultar_conteudo_vazio_lanca_erro_consulta_ia(monkeypatch):
    capturado = {}
    _instalar_groq_falso(monkeypatch, lambda **kwargs: _RespostaFalsa([_Escolha(None)]), capturado)

    with pytest.raises(ErroConsultaIA):
        consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")


def test_consultar_conteudo_nao_e_json_valido_lanca_erro_consulta_ia(monkeypatch):
    capturado = {}
    _instalar_groq_falso(monkeypatch, lambda **kwargs: _RespostaFalsa([_Escolha("isto nao e json{{{")]), capturado)

    with pytest.raises(ErroConsultaIA):
        consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")


def test_consultar_erro_do_sdk_vira_erro_consulta_ia(monkeypatch):
    # Cobre timeout, rate limit, erro de conexão, chave inválida, modelo
    # indisponível etc. de uma vez só — a captura em src/ia_cliente_groq.py é
    # ampla (não amarrada a uma exceção específica do SDK).
    capturado = {}

    def _levanta_erro(**kwargs):
        raise TimeoutError("a API não respondeu a tempo")

    _instalar_groq_falso(monkeypatch, _levanta_erro, capturado)

    with pytest.raises(ErroConsultaIA):
        consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")


def test_consultar_pacote_groq_ausente_vira_erro_consulta_ia(monkeypatch):
    # Idioma padrão do Python: sys.modules[nome] = None faz `import nome`
    # levantar ImportError, simulando o pacote não instalado.
    monkeypatch.setitem(sys.modules, "groq", None)

    with pytest.raises(ErroConsultaIA):
        consultar("sistema", "usuario", LABELS, modelo="openai/gpt-oss-120b", api_key="gsk-teste")
