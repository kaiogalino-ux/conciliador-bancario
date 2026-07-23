"""Camada de IA — 2ª etapa DECISIVA de conciliação (ver CLAUDE.md e
docs/HISTORICO_DECISOES.md para as regras completas).

Roda só depois de TODAS as fases determinísticas de `src/conciliador.py`,
sobre o que sobrar em `Status == "Revisão Manual"`. Este módulo é lógica pura
(sem rede) — quem fala com a Groq é `src/ia_cliente_groq.py`, injetado aqui
via o parâmetro `cliente_ia` para ficar 100% testável com um cliente falso e
determinístico.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from src.conciliador import (
    MOTIVO_EMPATE_NOME,
    MOTIVO_MULTIPLOS_CANDIDATOS,
    MOTIVO_NAO_ENCONTRADO_DIVERGENCIA_DATA,
    MOTIVO_NAO_ENCONTRADO_MULTIPLOS,
    MOTIVO_NAO_ENCONTRADO_SEM_EVIDENCIA,
    MOTIVO_NOME_INSUFICIENTE,
    MOTIVO_TOLERANCIA_SEM_EVIDENCIA,
    OBS_CONCILIADO_IA,
    STATUS_CONCILIADO,
    STATUS_REVISAO_MANUAL,
    TIPO_CONCILIACAO_IA,
    _classificar_tipo_lote,
    _linha_resultado_banco,
    _linha_resultado_erp,
)
from src.ia_cliente_groq import ErroConsultaIA
from src.ia_cliente_groq import consultar as _consultar_ia_padrao
from src.ia_config import IA_MODO_AUTOMATICO, ConfiguracaoIA

# Lista branca de motivos elegíveis (revisão 3 do plano da funcionalidade —
# ver docs/HISTORICO_DECISOES.md). Deliberadamente uma lista BRANCA, não
# negra: um motivo novo que vier a ser criado no futuro fica fora do escopo
# da IA por padrão, a menos que alguém o adicione aqui explicitamente.
#
# MOTIVO_NAO_ENCONTRADO_SEM_EVIDENCIA está incluído por completude (fazia
# parte da lista aprovada), mas hoje nunca é de fato produzido por
# src/conciliador.py (ver docs/HISTORICO_DECISOES.md, decisão 2026-07-10-d) —
# fica pronto para quando/se voltar a ser gerado.
#
# Removidos deliberadamente (nunca elegíveis, mesmo em Revisão Manual):
# MOTIVO_QUANTIDADE_DIVERGENTE, MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA,
# MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO, MOTIVO_SEM_DATA_PAGAMENTO,
# MOTIVO_REMUNERACAO_SEM_NOME, todos os MOTIVO_LOTE_*, MOTIVO_PAR_CONFLITANTE.
MOTIVOS_ELEGIVEIS_IA = frozenset(
    {
        MOTIVO_MULTIPLOS_CANDIDATOS,
        MOTIVO_NOME_INSUFICIENTE,
        MOTIVO_TOLERANCIA_SEM_EVIDENCIA,
        MOTIVO_EMPATE_NOME,
        MOTIVO_NAO_ENCONTRADO_SEM_EVIDENCIA,
        MOTIVO_NAO_ENCONTRADO_DIVERGENCIA_DATA,
        MOTIVO_NAO_ENCONTRADO_MULTIPLOS,
    }
)

# Colunas de auditoria da IA — só somadas a COLUNAS_RESULTADO quando
# IA_MODO != DESATIVADA (ver conciliar() em src/conciliador.py). Quando
# DESATIVADA, essas colunas não existem no Resultado.xlsx.
COLUNAS_IA = [
    "Decisão IA",
    "Confiança IA",
    "Motivo IA",
    "Validação IA",
    "Modelo IA",
]


def _elegivel_para_ia(linha: dict, df_erp: pd.DataFrame) -> bool:
    """Os 6 critérios simultâneos (ver docs/HISTORICO_DECISOES.md): só uma
    linha do lado ERP, em Revisão Manual, com motivo na lista branca, com
    Data ERP Usada preenchida, índice de origem conhecido e que não pertence
    a nenhum tipo de lote NET EMP, vira candidata a uma proposta da IA."""
    if linha.get("Status") != STATUS_REVISAO_MANUAL:
        return False
    if linha.get("Origem") != "ERP":
        return False

    i = linha.get("_erp_index")
    if i is None:
        return False

    if linha.get("Motivo Revisão") not in MOTIVOS_ELEGIVEIS_IA:
        return False

    data_erp = df_erp.at[i, "Data ERP Usada"]
    if data_erp is None or (isinstance(data_erp, float) and pd.isna(data_erp)) or pd.isna(data_erp):
        return False

    categoria = df_erp.at[i, "Categoria"] if "Categoria" in df_erp.columns else ""
    if _classificar_tipo_lote(df_erp.at[i, "Favorecido"], categoria) is not None:
        return False

    return True


def _selecionar_candidatos_banco(
    i, df_erp: pd.DataFrame, df_banco: pd.DataFrame, bancos_disponiveis, config_ia: ConfiguracaoIA
) -> list:
    """Pré-seleciona até `config_ia.maximo_candidatos` com valor absoluto
    exato e obrigatoriamente a mesma data. A trava não depende do valor
    recebido em `config_ia.janela_busca_dias`."""
    valor_alvo = round(abs(df_erp.at[i, "Valor"]), 2)
    data_alvo = df_erp.at[i, "Data ERP Usada"]

    candidatos = []
    for j in bancos_disponiveis:
        valor_banco = df_banco.at[j, "Valor"]
        if round(abs(valor_banco), 2) != valor_alvo:
            continue

        data_banco = df_banco.at[j, "Data"]
        if data_banco is None or pd.isna(data_banco):
            continue

        diferenca_dias = abs((data_alvo - data_banco).days)
        # Trava de negócio: nenhuma configuração pode permitir conciliação
        # entre lançamentos de datas diferentes.
        if diferenca_dias != 0:
            continue

        candidatos.append((diferenca_dias, j))

    candidatos.sort(key=lambda par: (par[0], par[1]))
    return [j for _, j in candidatos[: config_ia.maximo_candidatos]]


# ---------------------------------------------------------------------------
# Construção do prompt e validação estrutural da resposta
# ---------------------------------------------------------------------------

DECISOES_VALIDAS_IA = {"CONCILIAR", "MANTER_REVISAO", "NENHUM_CANDIDATO"}

# Valores Python-only da coluna "Decisão IA" — nunca vêm do modelo.
DECISAO_SEM_CANDIDATO = "Sem candidato disponível"
DECISAO_ERRO_CONSULTA = "Erro na consulta à IA"

# Valores da coluna "Validação IA".
VALIDACAO_NAO_APLICAVEL = "Não aplicável"
VALIDACAO_APROVADA_AUTOMATICO = "Aprovada e conciliado automaticamente"
VALIDACAO_APROVADA_SOMBRA = "Aprovada (modo sombra, não aplicado)"


def _construir_prompt(i, df_erp: pd.DataFrame, candidatos: list, df_banco: pd.DataFrame, motivo_revisao) -> tuple:
    """Monta (sistema, usuario, labels) para a consulta à IA — nunca envia a
    planilha inteira, só o lançamento do ERP em questão e os candidatos já
    pré-filtrados por regra objetiva."""
    labels = [f"C{numero + 1}" for numero in range(len(candidatos))]

    linha_erp = df_erp.loc[i]
    linhas_candidatos = [
        f"{label}: Data={df_banco.at[j, 'Data']}, Valor={abs(df_banco.at[j, 'Valor']):.2f}, "
        f"Descrição=\"{df_banco.at[j, 'Favorecido']}\""
        for label, j in zip(labels, candidatos)
    ]

    sistema = (
        "Você é a SEGUNDA camada de decisão de um sistema de conciliação bancária de contas a "
        "pagar. Regras determinísticas em Python já tentaram conciliar este lançamento primeiro "
        "e não conseguiram com segurança — você só entra depois delas, nunca antes. "
        "Sua única tarefa é decidir se o lançamento do ERP corresponde a UM dos candidatos "
        "bancários apresentados. Você só pode escolher entre os candidatos oferecidos "
        f"({', '.join(labels) if labels else 'nenhum'}) — nunca invente um candidato, um ID, uma "
        "data, um valor ou um nome que não estejam explicitamente nos dados fornecidos. Você "
        "nunca pode modificar valor, data, nome ou ID de nenhum lançamento — só escolher ou não "
        "escolher entre o que foi dado. Valor igual sozinho NUNCA é suficiente para concluir "
        "CONCILIAR — analise também nomes, abreviações, ordem das palavras, razão social, nome "
        "fantasia e descrições bancárias truncadas/abreviadas. Responda MANTER_REVISAO sempre "
        "que houver qualquer dúvida relevante. Responda NENHUM_CANDIDATO quando nenhum candidato "
        "for realmente compatível. Nunca use conhecimento externo sobre empresas, pessoas ou "
        "fornecedores — decida só com os dados apresentados nesta mensagem. Você nunca cria "
        "lançamentos novos e nunca recomenda reutilizar um lançamento bancário já usado. O campo "
        "\"confianca\" é a sua autoavaliação da decisão, não uma probabilidade estatística "
        "comprovada. Responda sempre no formato estruturado solicitado, nunca em texto livre."
    )
    usuario = (
        "Lançamento do ERP em Revisão Manual:\n"
        f"Data ERP Usada={linha_erp['Data ERP Usada']}, Valor={abs(linha_erp['Valor']):.2f}, "
        f"Favorecido=\"{linha_erp['Favorecido']}\", Motivo Revisão=\"{motivo_revisao or ''}\"\n\n"
        "Candidatos bancários disponíveis (mesmo valor absoluto e mesma data):\n"
        + "\n".join(linhas_candidatos)
    )
    return sistema, usuario, labels


def _validar_estrutura_resposta(resposta, labels_validos: list) -> dict | None:
    """Valida o schema `{decisao, candidato, confianca, motivo}` — qualquer
    desvio (campo ausente, decisão fora do enum, candidato fora da lista
    oferecida quando decisao=CONCILIAR, confiança fora de [0, 1], motivo
    vazio) é tratado como resposta inválida, nunca aplicada."""
    if not isinstance(resposta, dict):
        return None

    decisao = resposta.get("decisao")
    confianca = resposta.get("confianca")
    motivo = resposta.get("motivo")
    candidato = resposta.get("candidato")

    if decisao not in DECISOES_VALIDAS_IA:
        return None
    if isinstance(confianca, bool) or not isinstance(confianca, (int, float)):
        return None
    if not (0 <= confianca <= 1):
        return None
    if not isinstance(motivo, str) or not motivo.strip():
        return None

    if decisao == "CONCILIAR":
        if candidato not in labels_validos:
            return None
    else:
        candidato = None

    return {"decisao": decisao, "candidato": candidato, "confianca": float(confianca), "motivo": motivo.strip()}


# ---------------------------------------------------------------------------
# Proposta, revalidação e resolução de conflitos
# ---------------------------------------------------------------------------


@dataclass
class _Proposta:
    erp_index: int
    decisao_bruta: str
    banco_index: "int | None" = None
    confianca: "float | None" = None
    motivo_ia: str = ""
    validacao_fixa: "str | None" = None


def _proposta_sem_candidato(i, config_ia: ConfiguracaoIA) -> _Proposta:
    return _Proposta(
        erp_index=i,
        decisao_bruta=DECISAO_SEM_CANDIDATO,
        motivo_ia=(
            "Nenhum lançamento bancário disponível dentro dos critérios objetivos "
            "(mesmo valor absoluto e mesma data)."
        ),
        validacao_fixa=VALIDACAO_NAO_APLICAVEL,
    )


def _proposta_erro_consulta(i, detalhe: str) -> _Proposta:
    return _Proposta(
        erp_index=i,
        decisao_bruta=DECISAO_ERRO_CONSULTA,
        motivo_ia=detalhe,
        validacao_fixa="Rejeitada: falha na comunicação com a IA",
    )


def _proposta_resposta_invalida(i) -> _Proposta:
    return _Proposta(
        erp_index=i,
        decisao_bruta=DECISAO_ERRO_CONSULTA,
        motivo_ia="A IA respondeu em um formato que não pôde ser validado.",
        validacao_fixa="Rejeitada: resposta da IA em formato inválido",
    )


def _resolver_conflitos(propostas: list) -> set:
    """Regra explícita do usuário: se 2+ ERPs escolherem (CONCILIAR) o mesmo
    banco, NENHUMA das decisões conflitantes pode ser aplicada — nunca
    escolhe sozinho, mesma filosofia de `_consolidar_pares_conciliados`.
    Retorna o conjunto de `erp_index` que estão em conflito."""
    grupos: dict = {}
    for proposta in propostas:
        if proposta.decisao_bruta == "CONCILIAR" and proposta.banco_index is not None:
            grupos.setdefault(proposta.banco_index, []).append(proposta.erp_index)

    conflitantes: set = set()
    for lista_erp in grupos.values():
        if len(lista_erp) > 1:
            conflitantes.update(lista_erp)
    return conflitantes


def _revalidar_decisao(
    proposta: _Proposta, df_erp: pd.DataFrame, df_banco: pd.DataFrame, bancos_disponiveis: set,
    bancos_reservados_lote: set, config_ia: ConfiguracaoIA,
) -> tuple:
    """Segunda bateria de checagens do Python antes de aceitar um CONCILIAR
    (itens 2-4, 6-8 e 11 da revalidação — itens 1/5 já garantidos antes de
    chegar aqui, itens 9/10 resolvidos em `_resolver_conflitos`). Retorna
    (aprovado, motivo_rejeicao_ou_None, diferenca_dias_ou_None)."""
    i, j = proposta.erp_index, proposta.banco_index

    if j not in bancos_disponiveis:
        return False, "banco não está mais disponível", None
    if j in bancos_reservados_lote:
        return False, "banco pertence a um lote NET EMP", None

    valor_erp = round(abs(df_erp.at[i, "Valor"]), 2)
    valor_banco = round(abs(df_banco.at[j, "Valor"]), 2)
    if valor_erp != valor_banco:
        return False, "valor não bate exatamente", None

    data_erp = df_erp.at[i, "Data ERP Usada"]
    data_banco = df_banco.at[j, "Data"]
    if data_erp is None or pd.isna(data_erp) or data_banco is None or pd.isna(data_banco):
        return False, "data ausente", None

    diferenca_dias = abs((data_erp - data_banco).days)
    if diferenca_dias != 0:
        return False, "data diferente; conciliação exige a mesma data", diferenca_dias

    categoria = df_erp.at[i, "Categoria"] if "Categoria" in df_erp.columns else ""
    if _classificar_tipo_lote(df_erp.at[i, "Favorecido"], categoria) is not None:
        return False, "lançamento pertence a lote NET EMP/Folha/Salário/Férias/Rescisão/13º", diferenca_dias

    limite_confianca = (
        config_ia.confianca_minima_automatico if config_ia.modo == IA_MODO_AUTOMATICO
        else config_ia.confianca_minima_sombra
    )
    if proposta.confianca is None or proposta.confianca < limite_confianca:
        return False, f"confiança abaixo do mínimo ({limite_confianca:.2f})", diferenca_dias

    if config_ia.modo == IA_MODO_AUTOMATICO and diferenca_dias > config_ia.janela_automatica_dias:
        return (
            False,
            f"diferença de data acima do permitido para aplicação automática ({config_ia.janela_automatica_dias} dia(s))",
            diferenca_dias,
        )

    return True, None, diferenca_dias


# ---------------------------------------------------------------------------
# Aplicação (preenchimento de auditoria e, em AUTOMATICO, conciliação real)
# ---------------------------------------------------------------------------


def _texto_id_banco_sugerido(j, df_banco: pd.DataFrame) -> str:
    linha = df_banco.loc[j]
    return f"Banco #{j} — {linha['Data']} — R$ {abs(linha['Valor']):.2f} — {linha['Favorecido']}"


def _preencher_colunas_ia(linha: dict, decisao, confianca, motivo, id_banco_sugerido, validacao, modelo) -> None:
    linha["Decisão IA"] = decisao
    linha["Confiança IA"] = confianca
    linha["Motivo IA"] = motivo
    linha["Validação IA"] = validacao
    linha["Modelo IA"] = modelo


def aplicar_decisoes_ia(
    linhas_brutas: list,
    df_erp: pd.DataFrame,
    df_banco: pd.DataFrame,
    indices_banco_lote_reservados,
    config_ia: ConfiguracaoIA,
    logger: logging.Logger,
    cliente_ia=None,
) -> list:
    """Orquestra as 3 fases (Decidir -> Resolver conflitos -> Aplicar) e
    devolve uma nova lista de linhas prontas para `_consolidar_pares_conciliados`.

    Roda depois de todas as fases determinísticas e antes de
    `_consolidar_pares_conciliados()` — uma decisão `CONCILIAR` aplicada em
    `IA_MODO=AUTOMATICO` produz linhas no mesmo formato (`_par_id=(i, j)`) que
    qualquer fase determinística já produz, então a consolidação existente
    funde o par sem precisar de nenhuma alteração.
    """
    cliente_ia = cliente_ia or _consultar_ia_padrao

    bancos_reservados_lote = set(indices_banco_lote_reservados)
    bancos_consumidos = {
        linha["_banco_index"]
        for linha in linhas_brutas
        if linha.get("Status") == STATUS_CONCILIADO and linha.get("_banco_index") is not None
    }
    bancos_disponiveis = set(df_banco.index) - bancos_reservados_lote - bancos_consumidos

    mapa_linha_por_erp: dict = {
        linha["_erp_index"]: linha
        for linha in linhas_brutas
        if linha.get("Origem") == "ERP" and linha.get("_erp_index") is not None
    }
    mapa_linha_banco_por_indice: dict = {
        linha["_banco_index"]: linha
        for linha in linhas_brutas
        if linha.get("Origem") == "Banco" and linha.get("_banco_index") is not None
    }

    # Fase 1 — Decidir (idêntica para SOMBRA e AUTOMATICO).
    propostas: list = []
    processados: set = set()
    contagem_chamadas_ia = 0

    for linha in linhas_brutas:
        if not _elegivel_para_ia(linha, df_erp):
            continue

        i = linha["_erp_index"]
        if i in processados:  # defensivo — cada ERP só aparece 1 vez em linhas_brutas
            continue
        processados.add(i)

        candidatos = _selecionar_candidatos_banco(i, df_erp, df_banco, bancos_disponiveis, config_ia)
        if not candidatos:
            propostas.append(_proposta_sem_candidato(i, config_ia))
            continue

        sistema, usuario, labels = _construir_prompt(i, df_erp, candidatos, df_banco, linha.get("Motivo Revisão"))
        mapa_labels = dict(zip(labels, candidatos))

        try:
            contagem_chamadas_ia += 1
            resposta_bruta = cliente_ia(sistema, usuario, labels, modelo=config_ia.modelo, api_key=config_ia.api_key)
        except ErroConsultaIA as erro:
            logger.warning(f"Falha na consulta à IA para o lançamento ERP #{i}: {erro}")
            propostas.append(_proposta_erro_consulta(i, str(erro)))
            continue
        except Exception as erro:  # rede de segurança final — nunca derruba a conciliação
            logger.warning(f"Erro inesperado na consulta à IA para o lançamento ERP #{i}: {erro}")
            propostas.append(_proposta_erro_consulta(i, str(erro)))
            continue

        resposta = _validar_estrutura_resposta(resposta_bruta, labels)
        if resposta is None:
            logger.warning(f"Resposta da IA em formato inválido para o lançamento ERP #{i}: {resposta_bruta!r}")
            propostas.append(_proposta_resposta_invalida(i))
            continue

        banco_escolhido = mapa_labels.get(resposta["candidato"]) if resposta["decisao"] == "CONCILIAR" else None
        propostas.append(
            _Proposta(
                erp_index=i, decisao_bruta=resposta["decisao"], banco_index=banco_escolhido,
                confianca=resposta["confianca"], motivo_ia=resposta["motivo"],
            )
        )

    logger.info(f"Camada de IA ({config_ia.modo}): {len(propostas)} lançamento(s) elegível(is), {contagem_chamadas_ia} chamada(s) à IA.")

    # Fase 2 — Resolver conflitos entre propostas CONCILIAR.
    conflitantes = _resolver_conflitos(propostas)

    # Fase 3 — Aplicar (ou só registrar, em SOMBRA).
    ids_para_remover: set = set()
    linhas_banco_novas: list = []
    contagem_aplicadas = 0

    for proposta in propostas:
        linha_alvo = mapa_linha_por_erp.get(proposta.erp_index)
        if linha_alvo is None:
            continue  # defensivo — não deveria acontecer

        if proposta.validacao_fixa is not None:
            # "Modelo IA" só é preenchido quando uma chamada de verdade foi
            # feita (erro/resposta inválida) — "Sem candidato disponível"
            # nunca chega a chamar a IA (ver Fase 1), então fica vazio.
            modelo_exibido = None if proposta.decisao_bruta == DECISAO_SEM_CANDIDATO else config_ia.modelo
            _preencher_colunas_ia(
                linha_alvo, proposta.decisao_bruta, proposta.confianca, proposta.motivo_ia, None,
                proposta.validacao_fixa, modelo_exibido,
            )
            continue

        if proposta.decisao_bruta != "CONCILIAR":
            # MANTER_REVISAO / NENHUM_CANDIDATO — nada a aplicar em nenhum modo.
            _preencher_colunas_ia(
                linha_alvo, proposta.decisao_bruta, proposta.confianca, proposta.motivo_ia, None,
                VALIDACAO_NAO_APLICAVEL, config_ia.modelo,
            )
            continue

        id_banco_sugerido = _texto_id_banco_sugerido(proposta.banco_index, df_banco)

        if proposta.erp_index in conflitantes:
            _preencher_colunas_ia(
                linha_alvo, proposta.decisao_bruta, proposta.confianca, proposta.motivo_ia, id_banco_sugerido,
                "Rejeitada: conflito com outro lançamento pelo mesmo candidato bancário", config_ia.modelo,
            )
            continue

        aprovado, motivo_rejeicao, diferenca_dias = _revalidar_decisao(
            proposta, df_erp, df_banco, bancos_disponiveis, bancos_reservados_lote, config_ia,
        )
        if not aprovado:
            _preencher_colunas_ia(
                linha_alvo, proposta.decisao_bruta, proposta.confianca, proposta.motivo_ia, id_banco_sugerido,
                f"Rejeitada: {motivo_rejeicao}", config_ia.modelo,
            )
            continue

        if config_ia.modo != IA_MODO_AUTOMATICO:
            # SOMBRA: mesma análise/validação, nunca aplica.
            _preencher_colunas_ia(
                linha_alvo, proposta.decisao_bruta, proposta.confianca, proposta.motivo_ia, id_banco_sugerido,
                VALIDACAO_APROVADA_SOMBRA, config_ia.modelo,
            )
            continue

        # AUTOMATICO + aprovado: concilia de verdade, reaproveitando os
        # mesmos construtores de linha que qualquer fase determinística usa.
        i, j = proposta.erp_index, proposta.banco_index
        linha_banco_origem = df_banco.loc[j]

        nova_linha_erp = _linha_resultado_erp(
            df_erp.loc[i], STATUS_CONCILIADO, OBS_CONCILIADO_IA, TIPO_CONCILIACAO_IA,
            linha_banco_origem["Data"], linha_banco_origem["Valor"], linha_banco_origem["Favorecido"],
            diferenca_dias, par_id=(i, j),
        )
        _preencher_colunas_ia(
            nova_linha_erp, "CONCILIAR", proposta.confianca, proposta.motivo_ia, id_banco_sugerido,
            VALIDACAO_APROVADA_AUTOMATICO, config_ia.modelo,
        )

        nova_linha_banco = _linha_resultado_banco(
            linha_banco_origem, STATUS_CONCILIADO, OBS_CONCILIADO_IA, TIPO_CONCILIACAO_IA,
            df_erp.at[i, "Data ERP Usada"], df_erp.at[i, "Tipo Data ERP"], df_erp.at[i, "Valor"],
            df_erp.at[i, "Favorecido"], diferenca_dias,
            compensacao_original=df_erp.at[i, "Data de Compensação Original"],
            vencimento_original=df_erp.at[i, "Vencimento Original"], par_id=(i, j),
        )

        # Substituição atômica: as duas linhas novas já foram construídas com
        # sucesso antes de qualquer mutação de linhas_brutas. Substitui o
        # dict do ERP em-place (preserva identidade, evita depender de
        # posição em lista); a linha antiga do banco é marcada para remoção
        # (por identidade) e a nova é só anexada — nunca por posição, que
        # ficaria inválida a cada remoção.
        linha_alvo.clear()
        linha_alvo.update(nova_linha_erp)

        linha_banco_antiga = mapa_linha_banco_por_indice.get(j)
        if linha_banco_antiga is not None:
            ids_para_remover.add(id(linha_banco_antiga))
        else:
            logger.warning(f"Linha do banco #{j} não encontrada para remoção ao aplicar conciliação por IA.")
        linhas_banco_novas.append(nova_linha_banco)

        bancos_disponiveis.discard(j)  # nunca mais oferecido nesta execução
        contagem_aplicadas += 1

    if contagem_aplicadas:
        logger.info(f"Camada de IA ({config_ia.modo}): {contagem_aplicadas} lançamento(s) conciliado(s) automaticamente.")

    linhas_finais = [linha for linha in linhas_brutas if id(linha) not in ids_para_remover]
    linhas_finais.extend(linhas_banco_novas)
    return linhas_finais
