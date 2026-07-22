"""Único arquivo do projeto que fala com a API da Groq.

Isola completamente o SDK `groq`: o import é feito só dentro da função que
efetivamente chama a API (nunca no topo do módulo), para que o projeto
inteiro continue funcionando normalmente — inclusive `pytest` — mesmo sem o
pacote instalado, enquanto `IA_MODO=DESATIVADA`.

Usa Structured Outputs (`response_format={"type": "json_schema", ...,
"strict": true}`) — suportado pelo modelo padrão `openai/gpt-oss-120b` — para
forçar uma resposta 100% estruturada, nunca texto livre. Mesmo com
`strict=true`, `src/ia_revisor.py` revalida todos os campos de novo (nunca
confia cegamente no schema): o `enum` de `candidato` abaixo é sempre fixo
(C1..C5 + null), mesmo quando um lançamento tem menos de 5 candidatos reais —
quem garante que a IA só "escolhe" um candidato de fato oferecido naquela
chamada é `_validar_estrutura_resposta` em `src/ia_revisor.py` (confere
contra `labels_validos`, a lista real), não o schema em si.
"""

import json

NOME_SCHEMA = "decisao_conciliacao"


class ErroConsultaIA(Exception):
    """Qualquer falha ao consultar a IA (pacote ausente, chave/modelo ausente
    ou inválido, rede, timeout, rate limit, resposta vazia/recusada, JSON
    inválido, campo fora do schema). Nunca deve propagar para fora da camada
    de IA — quem chama trata isso como "manter em revisão"."""


def _schema_estruturado() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": NOME_SCHEMA,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "decisao": {
                        "type": "string",
                        "enum": ["CONCILIAR", "MANTER_REVISAO", "NENHUM_CANDIDATO"],
                    },
                    "candidato": {
                        "type": ["string", "null"],
                        "enum": ["C1", "C2", "C3", "C4", "C5", None],
                    },
                    "confianca": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "motivo": {
                        "type": "string",
                    },
                },
                "required": ["decisao", "candidato", "confianca", "motivo"],
                "additionalProperties": False,
            },
        },
    }


def consultar(
    sistema: str,
    usuario: str,
    labels_validos: list[str],
    modelo: str,
    api_key: str,
    timeout: float = 30.0,
) -> dict:
    """Chama a API da Groq com Structured Outputs (strict) e devolve o dict
    decodificado de `choices[0].message.content`. `modelo` e `api_key` vêm
    sempre de `ConfiguracaoIA` (src/ia_config.py) — nunca há valor fixo aqui.
    `labels_validos` não altera o schema (fixo, C1..C5+null) — só é usado
    depois, em `src/ia_revisor.py`, para revalidar a escolha de verdade."""
    try:
        import groq
    except ImportError as erro:
        raise ErroConsultaIA(f"Pacote 'groq' não está instalado: {erro}") from erro

    try:
        cliente = groq.Groq(api_key=api_key)
        resposta = cliente.chat.completions.create(
            model=modelo,
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
            response_format=_schema_estruturado(),
            timeout=timeout,
        )
    except ErroConsultaIA:
        raise
    except Exception as erro:
        raise ErroConsultaIA(f"Falha na comunicação com a API da Groq: {erro}") from erro

    escolhas = getattr(resposta, "choices", None) or []
    if not escolhas:
        raise ErroConsultaIA("Resposta da IA sem nenhuma escolha (choices vazio).")

    conteudo = getattr(escolhas[0].message, "content", None)
    if not conteudo or not conteudo.strip():
        raise ErroConsultaIA("Resposta da IA veio vazia ou recusada (sem conteúdo).")

    try:
        return json.loads(conteudo)
    except json.JSONDecodeError as erro:
        raise ErroConsultaIA(f"Resposta da IA não é um JSON válido: {erro}") from erro
