"""Regra de conciliação: compara ERP e Banco por Valor absoluto e Data.

Nunca cruza lançamentos por nome/favorecido como critério principal. A comparação
de valor é feita pelo valor absoluto, pois um pagamento (contas a pagar) pode
aparecer negativo no extrato bancário mesmo estando positivo no ERP (o banco já
chega filtrado só com débitos/saídas — ver src/leitor_banco.py).

A conciliação roda em fases, sempre tentando resolver individualmente antes de
recorrer a mecanismos mais amplos (nunca em bloco/resumo quando dá para
identificar um a um):

1. Correspondência exata: mesmo valor absoluto e mesma "Data ERP Usada"/Data do banco.
   Quando há mais de um lançamento de qualquer lado nessa combinação (duplicidade
   de valor e data), cada lançamento é resolvido individualmente, nessa ordem:
     a) mesma descrição normalizada dos dois lados e mesma quantidade nos dois
        lados -> pareados um a um ("Duplicidade idêntica individual" — ex.:
        tarifas bancárias repetidas idênticas);
     b) mesma descrição normalizada mas quantidades diferentes -> Revisão
        Manual ("Quantidade divergente...");
     c) descrição do ERP (enriquecida com o ano do Vencimento, quando ajuda a
        desambiguar) permite identificar uma única descrição no banco de forma
        inequívoca (desempate por termos relevantes, único e mútuo) ->
        "Valor, data e nome";
     d) duplicidade equivalente: o ERP distingue por número de documento/NF mas
        o banco não — quando o "fornecedor base" (descrição sem números/
        marcadores de documento) bate e a quantidade é igual dos dois lados,
        concilia individualmente -> "Duplicidade equivalente individual";
     e) o que sobrar sem identificação clara -> Revisão Manual.
   Um par único (1 ERP x 1 Banco) de um tipo de lote NET EMP (Salário/Folha,
   Férias, Rescisão, 13º) só concilia direto quando há nome/descrição forte
   compatível — valor+data sozinhos nunca "roubam" um candidato do lote por
   coincidência (Mudança 2026-07-10, ver docs/HISTORICO_DECISOES.md).
2. Tolerância: só para pagamentos individuais (nunca lote NET EMP — ver fase
   3), até `TOLERANCIA_DIAS_INDIVIDUAL` dia(s) entre a Data ERP Usada e a Data
   do banco, dentro do mesmo valor absoluto, e só quando há nome/favorecido/
   descrição forte compatível — um candidato único só por proximidade de data
   vira Revisão Manual, não Conciliado (Mudança 2026-07-10).
3. Lote NET EMPR: só para o que continuar sem par depois das fases 1 e 2 —
   classifica lançamentos do banco tipo "NET EMP/EMPR" (Salário/Folha, Férias,
   Rescisão ou 13º) ainda não conciliados e tenta fechar cada grupo (Data,
   Tipo — Data ERP Usada EXATAMENTE igual à Data do lote bancário, sem
   tolerância nenhuma), nesta ordem, sempre em centavos inteiros para evitar
   erro de arredondamento:
     a) total direto: soma de todos os candidatos do ERP contra a soma de
        todos os lançamentos do banco do grupo — bate exatamente, concilia
        tudo;
     b) combinação única: se o total do ERP for maior que o do banco, procura
        um subconjunto dos candidatos cuja soma feche exatamente o total do
        banco (busca meet-in-the-middle) — só concilia se existir EXATAMENTE
        UMA combinação possível; 2 ou mais -> Revisão Manual (nunca adivinha);
     c) nome/descrição: só quando o banco traz algum identificador individual
        (nome, CPF, documento) além do vocabulário genérico do lote — nunca
        para bancos genéricos como "PGTO SALARIO VIA NET EMP".
   Resolve lote a lote, sem reutilizar um item do ERP em mais de um lote.

Nunca adivinha uma conciliação: só marca "Conciliado" quando o pareamento é
inequívoco (par único, duplicata idêntica/equivalente com quantidades iguais,
desempate por termos mutuamente único, total direto do lote, ou uma única
combinação exata de valores).
"""

import logging
from collections import defaultdict

import pandas as pd

from src.ia_config import IA_MODO_DESATIVADA
from src.utils import (
    contem_alguma_palavra,
    extrair_termos_base,
    extrair_termos_relevantes,
    normalizar_descricao,
)

STATUS_CONCILIADO = "Conciliado"
STATUS_REVISAO_MANUAL = "Revisão Manual"
STATUS_NAO_ENCONTRADO_BANCO = "Não encontrado no banco"
STATUS_SOMENTE_BANCO = "Somente banco"

# Valores padronizados da coluna "Tipo Conciliação".
TIPO_VALOR_E_DATA = "Valor e data"
TIPO_VALOR_DATA_DESCRICAO = "Valor, data e descrição"
TIPO_VALOR_DATA_NOME = "Valor, data e nome"
TIPO_VALOR_DATA_TOLERANCIA = "Valor, data (tolerância 1 dia) e nome"
TIPO_DUPLICIDADE_IDENTICA = "Duplicidade idêntica individual"
TIPO_DUPLICIDADE_EQUIVALENTE = "Duplicidade equivalente individual"
TIPO_CONCILIACAO_LOTE_CONSOLIDADO = "Lote NET EMP consolidado por data"
TIPO_REVISAO_MANUAL = STATUS_REVISAO_MANUAL
TIPO_NAO_ENCONTRADO_BANCO = STATUS_NAO_ENCONTRADO_BANCO
TIPO_SOMENTE_BANCO = STATUS_SOMENTE_BANCO
# Camada de IA (2ª etapa decisiva — ver src/ia_revisor.py e
# docs/HISTORICO_DECISOES.md): só usado quando uma decisão CONCILIAR da IA é
# aplicada de verdade em IA_MODO=AUTOMATICO, depois de passar por todas as
# revalidações do Python. Nunca produzido pelas fases determinísticas acima.
TIPO_CONCILIACAO_IA = "IA validada pelo Python"
OBS_CONCILIADO_IA = (
    "Conciliado automaticamente pela camada de IA (IA_MODO=AUTOMATICO), validado pelo Python"
)

# Tolerância de data (revisada em 2026-07-10 — ver docs/HISTORICO_DECISOES.md):
# lote NET EMP nunca usa tolerância (Data Banco deve ser exatamente igual à
# Data ERP Usada — ver _e_candidato_lote_erp e _resolver_lote_net_empr).
# Pagamentos individuais (não-lote) usam TOLERANCIA_DIAS_INDIVIDUAL, e só
# conciliam automaticamente quando há nome/descrição forte compatível.
TOLERANCIA_DIAS_INDIVIDUAL = 1

# Desempate por nome/descrição é opcional e pode ser desligado sem afetar a
# conciliação principal (valor absoluto + data).
USAR_DESCRICAO_PARA_DESEMPATE = True

OBS_DESEMPATE_NOME = "Conciliado individualmente por nome/descrição"
OBS_DUPLICIDADE_IDENTICA = "Conciliado individualmente por duplicidade idêntica"
OBS_DUPLICIDADE_EQUIVALENTE = "Banco não distingue documento/NF; conciliado por quantidade, valor, data e fornecedor base"
OBS_QUANTIDADE_DIVERGENTE = "Quantidade divergente para mesma data, valor e descrição"
OBS_DUPLICIDADE_INSUFICIENTE = "Duplicidade de valor e data; nome/descrição insuficiente para desempate seguro"
OBS_REMUNERACAO_SEM_NOME = (
    "Remuneração/salário com valor e data batendo, mas sem nome/descrição forte — "
    "não conciliado automaticamente antes do lote"
)
OBS_TOLERANCIA_SEM_EVIDENCIA = "Candidato único dentro da tolerância de 1 dia, mas sem nome/descrição forte para confirmar"
OBS_RECUPERADO_NAO_ENCONTRADO = 'Conciliado após verificação de possível "Não encontrado no banco"'
# Regra 2026-07-10-d (ver docs/HISTORICO_DECISOES.md): na verificação final de
# "Não encontrado no banco", um candidato único por valor+data dos dois lados
# (ainda disponível, mutuamente único) concilia mesmo sem nome/descrição
# compatível — não existe ambiguidade operacional quando valor e data já são
# únicos. Observação específica para esse caso (sem nome), distinta da usada
# quando o nome também bate.
OBS_RECUPERADO_VALOR_DATA_UNICOS = 'Conciliado por valor e data únicos (verificação de possível "Não encontrado no banco")'

# Motivos padronizados da coluna "Motivo Revisão" (só preenchida quando
# Status == Revisão Manual) — usados para agrupar a aba "Diagnóstico Revisão
# Manual" (ver src/exportador.py). Os motivos de lote são só o prefixo fixo: o
# texto completo inclui total ERP, total banco, diferença e quantidades.
MOTIVO_MULTIPLOS_CANDIDATOS = "Duplicidade de valor e data sem descrição suficiente"
MOTIVO_NOME_INSUFICIENTE = "Descrição/nome incompatível"
MOTIVO_QUANTIDADE_DIVERGENTE = "Quantidade divergente"
MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA = "Possível duplicidade equivalente não resolvida"
# Motivos de lote NET EMP (regra 11 do CLAUDE.md) — a busca automática (total
# direto -> combinação única -> nome/descrição) nunca adivinha; cada motivo
# identifica exatamente em qual etapa o lote não pôde ser fechado.
MOTIVO_LOTE_ERP_MENOR_QUE_BANCO = "Total ERP candidato menor que total banco NET EMP"
MOTIVO_LOTE_MULTIPLAS_COMBINACOES = "Múltiplas combinações possíveis para o lote NET EMP"
MOTIVO_LOTE_NENHUMA_COMBINACAO = "Nenhuma combinação exata encontrada para o lote NET EMP"
MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO = "Banco genérico sem nome e sem combinação única possível"
# Motivos revisados/adicionados em 2026-07-10 (ver docs/HISTORICO_DECISOES.md):
# lote NET EMP não usa tolerância de data, e remuneração/salário/férias/
# rescisão/13º não pode ser consumida antes do lote só por valor+data.
MOTIVO_LOTE_DIVERGENCIA_DATA = "Divergência de data para lote NET EMP"
MOTIVO_REMUNERACAO_SEM_NOME = "Remuneração/salário sem nome/descrição forte antes do lote"
MOTIVO_TOLERANCIA_SEM_EVIDENCIA = "Possível par com divergência de data (sem nome/descrição forte)"
# Motivo revisado em 2026-07-10: Vencimento nunca é usado para conciliar (ver
# docs/HISTORICO_DECISOES.md) — uma linha do ERP sem nenhuma data de
# pagamento/compensação/confirmação real recebe este motivo, sem tentar casar
# com o banco usando o vencimento.
MOTIVO_SEM_DATA_PAGAMENTO = "ERP sem data de pagamento/compensação; vencimento não é usado para conciliação"
# Motivos da verificação final de "Não encontrado no banco" (2026-07-10, ver
# docs/HISTORICO_DECISOES.md): antes de finalizar um ERP como "Não encontrado
# no banco", o sistema verifica se existe um possível par bancário — nunca
# força a conciliação quando há risco (múltiplos candidatos, banco já
# consumido por outro lançamento), só concilia quando a evidência é segura.
MOTIVO_NAO_ENCONTRADO_SEM_EVIDENCIA = (
    "Existe lançamento bancário com mesmo valor e mesma data, mas sem evidência suficiente para conciliação automática"
)
MOTIVO_NAO_ENCONTRADO_DIVERGENCIA_DATA = "Possível par encontrado com divergência de data"
MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO = "Possível par bancário já consumido por outro lançamento"
MOTIVO_NAO_ENCONTRADO_MULTIPLOS = "Múltiplos bancos possíveis para ERP marcado como Não encontrado"
MOTIVO_NAO_ENCONTRADO_SEM_CANDIDATO = "Nenhum lançamento bancário com valor/data ou nome compatível encontrado"
# Motivo padrão da coluna "Motivo Não Conciliado" para o lado do banco sem
# nenhum lançamento do ERP correspondente (Status "Somente banco").
MOTIVO_SOMENTE_BANCO_SEM_ERP = "Nenhum lançamento do ERP corresponde a este lançamento bancário dentro do período conciliado"
# Regra 1 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): verificação
# defensiva de unicidade de par — nunca deveria disparar (cada fase só
# consome de pools pendentes disjuntos), mas se algum índice ERP ou Banco
# aparecer em mais de um par "Conciliado", nunca escolhe um sozinho.
MOTIVO_PAR_CONFLITANTE = "Mesmo lançamento ERP/Banco foi associado a mais de um par possível"
# Motivo novo (2026-07-10-c, ver docs/HISTORICO_DECISOES.md): dentro de um
# grupo de mesmo valor/data(±tolerância), um candidato tem sinal de nome mas
# esse sinal empata com outro candidato (ou o termo comum não é único no
# grupo) — nunca escolhe um dos dois sozinho.
MOTIVO_EMPATE_NOME = "Empate de nome entre múltiplos candidatos"

MOTIVOS_DIAGNOSTICO = [
    MOTIVO_LOTE_MULTIPLAS_COMBINACOES,
    MOTIVO_LOTE_NENHUMA_COMBINACAO,
    MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO,
    MOTIVO_LOTE_ERP_MENOR_QUE_BANCO,
    MOTIVO_LOTE_DIVERGENCIA_DATA,
    MOTIVO_REMUNERACAO_SEM_NOME,
    MOTIVO_MULTIPLOS_CANDIDATOS,
    MOTIVO_EMPATE_NOME,
    MOTIVO_TOLERANCIA_SEM_EVIDENCIA,
    MOTIVO_QUANTIDADE_DIVERGENTE,
    MOTIVO_NOME_INSUFICIENTE,
    MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA,
    MOTIVO_SEM_DATA_PAGAMENTO,
    MOTIVO_NAO_ENCONTRADO_MULTIPLOS,
    MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO,
    MOTIVO_NAO_ENCONTRADO_DIVERGENCIA_DATA,
    MOTIVO_NAO_ENCONTRADO_SEM_EVIDENCIA,
]

# Lote NET EMPR (salário, férias, rescisão ou 13º). Só é "lote claro" quando a
# descrição do banco tem um marcador NET EMP/EMPR/EMPRESA **e** um termo que
# indique claramente o tipo (salário, férias, rescisão, folha ou 13º) — nunca
# genérico. Descrições como "PAG COBRANCA NET EMPRESA" ou "PAGTO ELETRON
# COBRANCA" não têm nenhum termo de tipo, então seguem a conciliação
# individual normal em vez de virar lote.
PALAVRAS_MARCADOR_LOTE_BANCO = ["NET EMP", "NET EMPR", "NET EMPRESA"]
# Nunca aplicar a regra de lote a transferências individuais.
PALAVRAS_EXCLUSAO_LOTE_BANCO = ["PIX", "TED", "DOC", "TRANSFERENCIA INDIVIDUAL"]

# Classificação do tipo do lote (mesma ordem de prioridade usada tanto para
# classificar o lançamento do banco quanto para agrupar candidatos do ERP).
# "Salário/Folha" também aceita PRO-LABORE do lado do ERP.
TIPO_LOTE_SALARIO_FOLHA = "Salário/Folha"
TIPO_LOTE_FERIAS = "Férias"
TIPO_LOTE_RESCISAO = "Rescisão"
TIPO_LOTE_DECIMO_TERCEIRO = "13º salário"
TIPO_LOTE_GENERICO = "Lote NET EMPR"

PALAVRAS_TIPO_SALARIO_FOLHA = ["SALARIO", "REMUNERACAO", "FOLHA", "PRO-LABORE", "PRO LABORE"]
PALAVRAS_TIPO_FERIAS = ["FERIAS"]
PALAVRAS_TIPO_RESCISAO = ["RESCISAO"]
PALAVRAS_TIPO_DECIMO = ["13", "DECIMO"]
# União dos termos de tipo específico — usada para exigir um tipo claro antes
# de reservar um lançamento do banco como lote (nunca só pelo marcador NET EMP).
PALAVRAS_TIPO_LOTE_CLARO = (
    PALAVRAS_TIPO_SALARIO_FOLHA + PALAVRAS_TIPO_FERIAS + PALAVRAS_TIPO_RESCISAO + PALAVRAS_TIPO_DECIMO
)
# Regra 2026-07-10-d (ver docs/HISTORICO_DECISOES.md): "FGTS" nunca é lote NET
# EMP, mesmo quando o texto também contém "RESCISÃO"/"13" (ex.: "FGTS -
# RESCISÃO FULANO", "FGTS - 13ª da 2ª parcela") — depósitos de FGTS vão sempre
# para a Caixa Econômica Federal via guia própria, nunca são pagos junto com o
# lote de folha/salário da empresa. Sem essa exclusão, esses lançamentos
# ficavam bloqueados pela trava de "remuneração sem nome" (regra geral, não é
# exceção de fornecedor — vale para qualquer lançamento com "FGTS" no texto).
PALAVRAS_EXCLUSAO_TIPO_LOTE_ERP = ["FGTS"]

# Prefixo do ID Lote por tipo (ex.: "FERIAS-2026-05-12-001").
PREFIXO_ID_LOTE = {
    TIPO_LOTE_SALARIO_FOLHA: "SALARIO",
    TIPO_LOTE_FERIAS: "FERIAS",
    TIPO_LOTE_RESCISAO: "RESCISAO",
    TIPO_LOTE_DECIMO_TERCEIRO: "DECIMO13",
    TIPO_LOTE_GENERICO: "LOTE",
}

OBS_LOTE_CONSOLIDADO = "Conciliado por lote NET EMP; total ERP restante bate com total banco NET EMP da data"

# Lote fechado por combinação exata única (regras 3b e 8 do CLAUDE.md): quando
# o total do ERP é maior que o total do banco, mas existe exatamente UM
# subconjunto dos candidatos cuja soma bate exatamente com o banco.
TIPO_LOTE_COMBINACAO_UNICA = "Lote NET EMP por combinação exata única"
OBS_LOTE_COMBINACAO_UNICA = "Conciliado por combinação única de valores ERP que soma exatamente o banco NET EMP"
OBS_LOTE_EXCLUIDO_COMBINACAO = (
    "Excluído do lote NET EMP: não faz parte da combinação exata única que soma o total do banco NET EMP"
)

# Lote fechado por nome/descrição (regra 3c do CLAUDE.md): só quando o banco
# traz um identificador individual (nome, CPF, documento) além do vocabulário
# genérico do lote — nunca para bancos genéricos como "PGTO SALARIO VIA NET EMP".
TIPO_LOTE_POR_NOME = "Lote NET EMP por nome/descrição individual"
OBS_LOTE_POR_NOME = "Conciliado individualmente por nome/descrição dentro do lote NET EMP"
OBS_LOTE_EXCLUIDO_NOME = (
    "Excluído do lote NET EMP: não identificado por nome/descrição entre os lançamentos do banco deste lote"
)

COLUNAS_RESULTADO = [
    "Data ERP Usada",
    "Tipo Data ERP",
    "Data de Compensação Original",
    "Vencimento Original",
    "Data Banco",
    "Valor ERP",
    "Valor Banco",
    "Favorecido",
    "Descrição ERP",
    "Descrição Banco",
    "Status",
    "Tipo Conciliação",
    "Observações",
    "Motivo Revisão",
    "Motivo Não Conciliado",
    "Diferença de Dias",
    "ID Lote",
    "Possível Data Banco",
    "Possível Valor Banco",
    "Possível Descrição Banco",
    "Status do Possível Banco",
    "Origem",
]


def _linha_resultado_erp(
    linha, status, obs, tipo_conciliacao, data_banco, valor_banco, descricao_banco, diferenca_dias,
    id_lote=None, motivo_revisao=None, par_id=None, motivo_nao_conciliado=None,
    possivel_data_banco=None, possivel_valor_banco=None, possivel_descricao_banco=None,
    status_possivel_banco=None,
) -> dict:
    return {
        "Data ERP Usada": linha["Data ERP Usada"],
        "Tipo Data ERP": linha["Tipo Data ERP"],
        "Data de Compensação Original": linha["Data de Compensação Original"],
        "Vencimento Original": linha["Vencimento Original"],
        "Data Banco": data_banco,
        "Valor ERP": linha["Valor"],
        "Valor Banco": valor_banco,
        "Favorecido": linha["Favorecido"],
        "Descrição ERP": linha["Favorecido"],
        "Descrição Banco": descricao_banco,
        "Status": status,
        "Tipo Conciliação": tipo_conciliacao,
        "Observações": obs,
        "Motivo Revisão": motivo_revisao,
        "Motivo Não Conciliado": motivo_nao_conciliado,
        "Diferença de Dias": diferenca_dias,
        "ID Lote": id_lote,
        "Possível Data Banco": possivel_data_banco,
        "Possível Valor Banco": possivel_valor_banco,
        "Possível Descrição Banco": possivel_descricao_banco,
        "Status do Possível Banco": status_possivel_banco,
        "Origem": "ERP",
        "_par_id": par_id,
        # Índice de origem em df_erp/df_banco (usado pela camada de IA — nunca
        # exportado, pois não está em COLUNAS_RESULTADO/COLUNAS_IA). `linha` é
        # sempre um `df_erp.loc[i]`, então `linha.name` já é o índice `i`; o
        # índice do banco só é conhecido aqui quando o par já foi confirmado
        # (par_id=(i, j)).
        "_erp_index": linha.name,
        "_banco_index": par_id[1] if par_id is not None else None,
    }


def _linha_resultado_banco(
    linha, status, obs, tipo_conciliacao, data_erp, tipo_data_erp, valor_erp, descricao_erp, diferenca_dias,
    id_lote=None, motivo_revisao=None, compensacao_original=None, vencimento_original=None,
    par_id=None, motivo_nao_conciliado=None,
) -> dict:
    return {
        "Data ERP Usada": data_erp,
        "Tipo Data ERP": tipo_data_erp,
        "Data de Compensação Original": compensacao_original,
        "Vencimento Original": vencimento_original,
        "Data Banco": linha["Data"],
        "Valor ERP": valor_erp,
        "Valor Banco": linha["Valor"],
        "Favorecido": linha["Favorecido"],
        "Descrição ERP": descricao_erp,
        "Descrição Banco": linha["Favorecido"],
        "Status": status,
        "Tipo Conciliação": tipo_conciliacao,
        "Observações": obs,
        "Motivo Revisão": motivo_revisao,
        "Motivo Não Conciliado": motivo_nao_conciliado,
        "Diferença de Dias": diferenca_dias,
        "ID Lote": id_lote,
        "Possível Data Banco": None,
        "Possível Valor Banco": None,
        "Possível Descrição Banco": None,
        "Status do Possível Banco": None,
        "Origem": "Banco",
        "_par_id": par_id,
        # Ver comentário equivalente em _linha_resultado_erp: `linha` é sempre
        # um `df_banco.loc[j]`, então `linha.name` já é o índice `j`.
        "_banco_index": linha.name,
        "_erp_index": par_id[0] if par_id is not None else None,
    }


def _consolidar_pares_conciliados(linhas: list, logger: logging.Logger) -> list:
    """Regra 1 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): cada par ERP x
    Banco efetivamente conciliado deve aparecer em uma única linha do
    Resultado — nunca uma linha "do lado ERP" e outra espelhada "do lado
    Banco" para o mesmo par. Só se aplica a pares 1-para-1 inequívocos
    (marcados com `_par_id=(índice_erp, índice_banco)` na origem); grupos de
    lote com mais de um lançamento de qualquer lado nunca recebem `_par_id` e
    continuam com uma linha por lançamento, como sempre (nunca resumidos).

    Verificação defensiva (regra 1, item 8 do pedido): se o mesmo índice ERP
    ou o mesmo índice Banco aparecer em mais de um par (não deveria acontecer,
    já que cada fase só consome de pools pendentes disjuntos), nunca escolhe
    um sozinho — rebaixa essas linhas para Revisão Manual com motivo
    explícito, sem apagar nenhuma delas.
    """
    # Conta por PAR único (não por linha — cada par legítimo já aparece em 2
    # linhas espelhadas antes da consolidação, o que não é conflito nenhum).
    pares_unicos: set = {linha["_par_id"] for linha in linhas if linha.get("_par_id") is not None}
    contagem_erp: dict = {}
    contagem_banco: dict = {}
    for i, j in pares_unicos:
        contagem_erp[i] = contagem_erp.get(i, 0) + 1
        contagem_banco[j] = contagem_banco.get(j, 0) + 1

    erp_conflitantes = {i for i, n in contagem_erp.items() if n > 1}
    banco_conflitantes = {j for j, n in contagem_banco.items() if n > 1}

    vistos: set = set()
    consolidadas: list = []
    for linha in linhas:
        par_id = linha.pop("_par_id", None)
        if par_id is None:
            consolidadas.append(linha)
            continue

        i, j = par_id
        if i in erp_conflitantes or j in banco_conflitantes:
            if par_id in vistos:
                continue
            vistos.add(par_id)
            logger.warning(
                f"Conflito de par conciliado detectado (ERP #{i} / Banco #{j}) — "
                "marcado como Revisão Manual em vez de escolher automaticamente."
            )
            linha["Status"] = STATUS_REVISAO_MANUAL
            linha["Tipo Conciliação"] = TIPO_REVISAO_MANUAL
            linha["Motivo Revisão"] = MOTIVO_PAR_CONFLITANTE
            consolidadas.append(linha)
            continue

        if par_id in vistos:
            continue
        vistos.add(par_id)
        linha["Origem"] = "ERP+Banco"
        consolidadas.append(linha)

    return consolidadas


def _texto_comparacao_erp(df_erp: pd.DataFrame, i) -> str:
    """Texto usado no desempate por nome: descrição do ERP enriquecida com o ano
    do Vencimento, quando disponível. É frequentemente o único lugar, em
    relatórios do GestãoClick, onde esse ano aparece — a Data de compensação (ou
    o fallback de confirmação) usada na conciliação principal costuma ser a mesma
    para lançamentos que só diferem pelo ano de vencimento (ex.: "Licenciamento
    CAMINHÃO" com Vencimento 2022 x 2023).
    """
    texto = df_erp.at[i, "Favorecido"]
    vencimento = df_erp.at[i, "Vencimento Original"] if "Vencimento Original" in df_erp.columns else None
    if vencimento is not None and not pd.isna(vencimento):
        return f"{texto} {vencimento.year}"
    return texto


def _termos_compativeis(termo_a: str, termo_b: str) -> bool:
    """Regra 3 (2026-07-10-c, ver docs/HISTORICO_DECISOES.md): dois termos são
    compatíveis quando são idênticos, ou quando um é prefixo do outro — nome
    truncado pelo banco (ex.: "SILV" compatível com "SILVA", "ALM" compatível
    com "ALMEIDA"). Ambos os termos já têm pelo menos 3 caracteres, garantido
    por `extrair_termos_relevantes`."""
    if termo_a == termo_b:
        return True
    menor, maior = (termo_a, termo_b) if len(termo_a) <= len(termo_b) else (termo_b, termo_a)
    return maior.startswith(menor)


def _termos_correspondentes(termos_a: set[str], termos_b: set[str]) -> list[tuple[str, str]]:
    """Empareia os termos de dois conjuntos — primeiro por igualdade exata,
    depois por truncamento (regra 3) — cada termo usado no máximo 1 vez de
    cada lado. Retorna a lista de pares (termo_a, termo_b) que casaram; o
    tamanho dessa lista é a pontuação do par (regra 3: 2+ = forte, 1 = precisa
    ser único no grupo, 0 = nunca concilia sozinho)."""
    pares: list[tuple[str, str]] = []
    usados_b: set[str] = set()

    exatos = sorted(termos_a & termos_b)
    for termo in exatos:
        pares.append((termo, termo))
        usados_b.add(termo)

    for termo_a in sorted(termos_a - set(exatos)):
        for termo_b in sorted(termos_b - usados_b):
            if _termos_compativeis(termo_a, termo_b):
                pares.append((termo_a, termo_b))
                usados_b.add(termo_b)
                break

    return pares


def _nome_compativel(texto_a, texto_b) -> bool:
    """Evidência de nome/favorecido/descrição entre dois textos: pelo menos 1
    termo relevante (nome próprio, número de documento etc.) em comum — exato
    ou truncado (regra 3, 2026-07-10-c). Usado para exigir esse sinal em par
    único (Mudança 2026-07-10): valor+data sozinhos não bastam para
    remuneração/lote nem para tolerância de data individual."""
    return bool(_termos_correspondentes(extrair_termos_relevantes(texto_a), extrair_termos_relevantes(texto_b)))


def _agrupar_por_descricao_normalizada(df: pd.DataFrame, indices: list) -> dict:
    """Agrupa índices por descrição normalizada. Retorna {texto: [índices]}."""
    grupos: dict = {}
    for indice in indices:
        texto = normalizar_descricao(df.at[indice, "Favorecido"])
        grupos.setdefault(texto, []).append(indice)
    return grupos


def _desempatar_por_nome(
    indices_erp: list, indices_banco: list, df_erp: pd.DataFrame, df_banco: pd.DataFrame,
    pares_permitidos: set[tuple] | None = None,
) -> dict:
    """Tenta casar, dentro de um grupo ambíguo (mesmo valor absoluto e mesma
    data, ou mesmo valor dentro da tolerância de data — regra 2026-07-10-c),
    lançamentos ERP e Banco comparando os termos relevantes (nomes próprios,
    números de documento etc.) que sobram depois de remover o genérico.

    `pares_permitidos`, quando informado, restringe a comparação só aos pares
    (i, j) permitidos (usado pela fase de tolerância — só faz sentido comparar
    nome entre um ERP e um Banco que já estão dentro da janela de dias).

    - 2 ou mais termos compatíveis (exatos ou truncados, regra 3) -> correspondência
      forte, considerada válida sempre.
    - Só 1 termo compatível -> só vale se esse par específico de termos não
      aparecer em nenhum outro par candidato do mesmo grupo (senão é ambíguo
      demais para decidir sozinho — regra 4, "não pode haver empate").
    Dentre os pares válidos, só confirma quem for a única correspondência válida
    dos dois lados (nunca adivinha); repete até não sobrar mais progresso.
    """
    termos_erp = {i: extrair_termos_relevantes(_texto_comparacao_erp(df_erp, i)) for i in indices_erp}
    termos_banco = {j: extrair_termos_relevantes(df_banco.at[j, "Favorecido"]) for j in indices_banco}

    pontuacao: dict = {}
    correspondencias: dict = {}
    pares_por_correspondencia: dict = {}
    for i in indices_erp:
        for j in indices_banco:
            if pares_permitidos is not None and (i, j) not in pares_permitidos:
                continue
            pares_termos = _termos_correspondentes(termos_erp[i], termos_banco[j])
            if not pares_termos:
                continue
            pontuacao[(i, j)] = len(pares_termos)
            correspondencias[(i, j)] = pares_termos
            for par_termo in pares_termos:
                pares_por_correspondencia.setdefault(par_termo, []).append((i, j))

    def par_e_valido(i, j) -> bool:
        if pontuacao[(i, j)] >= 2:
            return True
        (par_termo,) = correspondencias[(i, j)]
        return len(pares_por_correspondencia[par_termo]) == 1

    candidatos_validos = {par for par in pontuacao if par_e_valido(*par)}

    confirmados: dict = {}
    restantes_erp = set(indices_erp)
    restantes_banco = set(indices_banco)

    progrediu = True
    while progrediu:
        progrediu = False
        pares_atuais = [(i, j) for (i, j) in candidatos_validos if i in restantes_erp and j in restantes_banco]

        candidatos_de_erp: dict = {}
        candidatos_de_banco: dict = {}
        for i, j in pares_atuais:
            candidatos_de_erp.setdefault(i, []).append(j)
            candidatos_de_banco.setdefault(j, []).append(i)

        for i, j in pares_atuais:
            if len(candidatos_de_erp[i]) == 1 and len(candidatos_de_banco[j]) == 1:
                confirmados[i] = j
                restantes_erp.discard(i)
                restantes_banco.discard(j)
                progrediu = True

    return confirmados


def _resolver_duplicidade_equivalente(
    indices_erp: list, indices_banco: list, df_erp: pd.DataFrame, df_banco: pd.DataFrame
) -> tuple[list, set, set]:
    """Etapa 3: quando o ERP distingue por número de documento/NF mas o banco
    não, agrupa por "fornecedor base" (descrição sem números/marcadores de
    documento) e concilia individualmente quando há exatamente 1 cluster do
    banco compatível (por contenção de termos, nos dois sentidos) com exatamente
    1 cluster do ERP, e a quantidade de lançamentos bate — nunca quando há mais
    de um candidato concorrente.

    Retorna (confirmados, envolvidos_erp, envolvidos_banco): `confirmados` é uma
    lista de (lista_erp, lista_banco) já pareáveis 1 a 1; `envolvidos_*` marca
    índices que tiveram algum indício de duplicidade equivalente mas não foram
    confirmados (usado só para dar um motivo de Revisão Manual mais específico).
    """
    termos_erp = {i: extrair_termos_base(df_erp.at[i, "Favorecido"]) for i in indices_erp}
    termos_banco = {j: extrair_termos_base(df_banco.at[j, "Favorecido"]) for j in indices_banco}

    grupos_erp: dict = {}
    for i, termos in termos_erp.items():
        if termos:
            grupos_erp.setdefault(frozenset(termos), []).append(i)

    grupos_banco: dict = {}
    for j, termos in termos_banco.items():
        if termos:
            grupos_banco.setdefault(frozenset(termos), []).append(j)

    def compativeis(termos_a: frozenset, termos_b: frozenset) -> bool:
        return termos_a <= termos_b or termos_b <= termos_a

    confirmados: list = []
    envolvidos_erp: set = set()
    envolvidos_banco: set = set()

    for termos_e, lista_erp in grupos_erp.items():
        candidatos = [tb for tb in grupos_banco if compativeis(termos_e, tb)]
        if not candidatos:
            continue

        envolvidos_erp.update(lista_erp)
        for tb in candidatos:
            envolvidos_banco.update(grupos_banco[tb])

        if len(candidatos) != 1:
            continue

        termos_b = candidatos[0]
        candidatos_reversos = [te for te in grupos_erp if compativeis(te, termos_b)]
        if len(candidatos_reversos) != 1:
            continue

        lista_banco = grupos_banco[termos_b]
        if len(lista_erp) != len(lista_banco):
            continue

        confirmados.append((lista_erp, lista_banco))

    for lista_erp, lista_banco in confirmados:
        envolvidos_erp.difference_update(lista_erp)
        envolvidos_banco.difference_update(lista_banco)

    return confirmados, envolvidos_erp, envolvidos_banco


def _resolver_grupo_ambiguo(
    indices_erp: list, indices_banco: list, df_erp: pd.DataFrame, df_banco: pd.DataFrame,
    e_candidato_lote_erp=None,
) -> tuple[list, list]:
    """Resolve individualmente (nunca em bloco) um grupo com o mesmo valor absoluto
    e a mesma data, mas com mais de um lançamento de algum lado.

    Quando um lançamento do ERP não tem nenhum sinal seguro (Passo 4) e
    `e_candidato_lote_erp(i)` diz que ele é um candidato de lote NET EMP com um
    lote bancário claro do mesmo tipo por perto, ele não é finalizado como
    Revisão Manual aqui — fica de fora de `linhas` e é reportado em
    `indices_erp_adiados` para a etapa de lote tentar (ver conciliar()). Isso
    evita que uma coincidência de valor/data com um lançamento comum "roube"
    um candidato legítimo de lote antes da hora, sem precisar bloqueá-lo de
    antemão (decisão revisada em 2026-07-10 — ver docs/HISTORICO_DECISOES.md).

    Retorna (linhas, indices_erp_adiados).
    """
    linhas = []
    indices_erp_adiados: list = []
    resolvidos_erp, resolvidos_banco = set(), set()

    grupos_erp = _agrupar_por_descricao_normalizada(df_erp, indices_erp)
    grupos_banco = _agrupar_por_descricao_normalizada(df_banco, indices_banco)

    # Passo 1: mesma descrição normalizada nos dois lados. Quando o grupo tem só
    # 1 lançamento de cada lado, a própria descrição já identifica uma
    # correspondência única — "duplicidade idêntica" só se aplica quando há de
    # fato mais de um lançamento repetido.
    for texto, lista_erp in grupos_erp.items():
        lista_banco = grupos_banco.get(texto)
        if not lista_banco:
            continue

        if len(lista_erp) == len(lista_banco):
            if len(lista_erp) == 1:
                tipo, obs = TIPO_VALOR_DATA_DESCRICAO, "Conciliado individualmente por descrição"
            else:
                tipo, obs = TIPO_DUPLICIDADE_IDENTICA, OBS_DUPLICIDADE_IDENTICA

            for i, j in zip(sorted(lista_erp), sorted(lista_banco)):
                linha_erp, linha_banco = df_erp.loc[i], df_banco.loc[j]
                linhas.append(_linha_resultado_erp(
                    linha_erp, STATUS_CONCILIADO, obs, tipo,
                    linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0, par_id=(i, j),
                ))
                linhas.append(_linha_resultado_banco(
                    linha_banco, STATUS_CONCILIADO, obs, tipo,
                    linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
                    compensacao_original=linha_erp["Data de Compensação Original"],
                    vencimento_original=linha_erp["Vencimento Original"], par_id=(i, j),
                ))
        else:
            referencia_banco = df_banco.loc[lista_banco[0]] if len(lista_banco) == 1 else None
            for i in lista_erp:
                linha_erp = df_erp.loc[i]
                linhas.append(_linha_resultado_erp(
                    linha_erp, STATUS_REVISAO_MANUAL, OBS_QUANTIDADE_DIVERGENTE, TIPO_REVISAO_MANUAL,
                    referencia_banco["Data"] if referencia_banco is not None else pd.NaT,
                    referencia_banco["Valor"] if referencia_banco is not None else None,
                    referencia_banco["Favorecido"] if referencia_banco is not None else None,
                    0 if referencia_banco is not None else None,
                    motivo_revisao=MOTIVO_QUANTIDADE_DIVERGENTE,
                ))
            referencia_erp = df_erp.loc[lista_erp[0]] if len(lista_erp) == 1 else None
            for j in lista_banco:
                linha_banco = df_banco.loc[j]
                linhas.append(_linha_resultado_banco(
                    linha_banco, STATUS_REVISAO_MANUAL, OBS_QUANTIDADE_DIVERGENTE, TIPO_REVISAO_MANUAL,
                    referencia_erp["Data ERP Usada"] if referencia_erp is not None else pd.NaT,
                    referencia_erp["Tipo Data ERP"] if referencia_erp is not None else "",
                    referencia_erp["Valor"] if referencia_erp is not None else None,
                    referencia_erp["Favorecido"] if referencia_erp is not None else None,
                    0 if referencia_erp is not None else None,
                    motivo_revisao=MOTIVO_QUANTIDADE_DIVERGENTE,
                    compensacao_original=referencia_erp["Data de Compensação Original"] if referencia_erp is not None else None,
                    vencimento_original=referencia_erp["Vencimento Original"] if referencia_erp is not None else None,
                ))

        resolvidos_erp.update(lista_erp)
        resolvidos_banco.update(lista_banco)

    # Passo 2: para o que sobrou, desempate por nome/descrição único e mútuo
    # (nomes próprios, números de documento etc.).
    restantes_erp = [i for i in indices_erp if i not in resolvidos_erp]
    restantes_banco = [j for j in indices_banco if j not in resolvidos_banco]

    confirmados_nome = (
        _desempatar_por_nome(restantes_erp, restantes_banco, df_erp, df_banco)
        if USAR_DESCRICAO_PARA_DESEMPATE
        else {}
    )

    for i, j in confirmados_nome.items():
        linha_erp, linha_banco = df_erp.loc[i], df_banco.loc[j]
        linhas.append(_linha_resultado_erp(
            linha_erp, STATUS_CONCILIADO, OBS_DESEMPATE_NOME, TIPO_VALOR_DATA_NOME,
            linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0, par_id=(i, j),
        ))
        linhas.append(_linha_resultado_banco(
            linha_banco, STATUS_CONCILIADO, OBS_DESEMPATE_NOME, TIPO_VALOR_DATA_NOME,
            linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
            compensacao_original=linha_erp["Data de Compensação Original"],
            vencimento_original=linha_erp["Vencimento Original"], par_id=(i, j),
        ))

    restantes_erp = [i for i in restantes_erp if i not in confirmados_nome]
    restantes_banco = [j for j in restantes_banco if j not in confirmados_nome.values()]

    # Passo 3: duplicidade equivalente — ERP distingue por documento/NF, banco
    # não; concilia por fornecedor base quando a quantidade bate e não há
    # candidato concorrente.
    combinacoes_equivalentes, envolvidos_erp, envolvidos_banco = _resolver_duplicidade_equivalente(
        restantes_erp, restantes_banco, df_erp, df_banco
    )

    usados_erp_equiv, usados_banco_equiv = set(), set()
    for lista_erp, lista_banco in combinacoes_equivalentes:
        for i, j in zip(sorted(lista_erp), sorted(lista_banco)):
            linha_erp, linha_banco = df_erp.loc[i], df_banco.loc[j]
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_CONCILIADO, OBS_DUPLICIDADE_EQUIVALENTE, TIPO_DUPLICIDADE_EQUIVALENTE,
                linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0, par_id=(i, j),
            ))
            linhas.append(_linha_resultado_banco(
                linha_banco, STATUS_CONCILIADO, OBS_DUPLICIDADE_EQUIVALENTE, TIPO_DUPLICIDADE_EQUIVALENTE,
                linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
                compensacao_original=linha_erp["Data de Compensação Original"],
                vencimento_original=linha_erp["Vencimento Original"], par_id=(i, j),
            ))
        usados_erp_equiv.update(lista_erp)
        usados_banco_equiv.update(lista_banco)

    restantes_erp = [i for i in restantes_erp if i not in usados_erp_equiv]
    restantes_banco = [j for j in restantes_banco if j not in usados_banco_equiv]

    # Passo 4: o que continuar ambíguo vira Revisão Manual. Motivo mais
    # específico quando há indício de duplicidade equivalente não confirmada,
    # ou quando sobrou só 1 candidato do outro lado mas o nome não confirmou;
    # "múltiplos candidatos" quando ainda há mais de uma possibilidade em aberto.
    # Exceção: um candidato de lote NET EMP sem sinal seguro aqui é adiado para
    # a etapa de lote em vez de finalizado (ver docstring da função).
        # Quando restar exatamente um ERP e um Banco, os dois representam
    # o mesmo possível par. O par continua em Revisão Manual, mas será
    # apresentado em uma única linha no Resultado.xlsx.
    par_id_revisao_unico = (
        (restantes_erp[0], restantes_banco[0])
        if (
            len(restantes_erp) == 1
            and len(restantes_banco) == 1
            and not (
                e_candidato_lote_erp is not None
                and e_candidato_lote_erp(restantes_erp[0])
            )
        )
        else None
    )
    for i in restantes_erp:
        if e_candidato_lote_erp is not None and e_candidato_lote_erp(i):
            indices_erp_adiados.append(i)
            continue

        linha_erp = df_erp.loc[i]
        if i in envolvidos_erp:
            motivo = MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA
        elif len(restantes_banco) == 1:
            motivo = MOTIVO_NOME_INSUFICIENTE
        else:
            motivo = MOTIVO_MULTIPLOS_CANDIDATOS

        if len(restantes_banco) == 1:
            linha_banco = df_banco.loc[restantes_banco[0]]
            data_banco, valor_banco, descricao_banco, diferenca_dias = (
                linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0
            )
        else:
            data_banco, valor_banco, descricao_banco, diferenca_dias = pd.NaT, None, None, None
        linhas.append(_linha_resultado_erp(
            linha_erp, STATUS_REVISAO_MANUAL, OBS_DUPLICIDADE_INSUFICIENTE, TIPO_REVISAO_MANUAL,
                        data_banco, valor_banco, descricao_banco, diferenca_dias,
            motivo_revisao=motivo,
            par_id=par_id_revisao_unico,
        
        ))

    for j in restantes_banco:
        linha_banco = df_banco.loc[j]
        if j in envolvidos_banco:
            motivo = MOTIVO_DUPLICIDADE_EQUIVALENTE_NAO_RESOLVIDA
        elif len(restantes_erp) == 1:
            motivo = MOTIVO_NOME_INSUFICIENTE
        else:
            motivo = MOTIVO_MULTIPLOS_CANDIDATOS

        if len(restantes_erp) == 1:
            linha_erp = df_erp.loc[restantes_erp[0]]
            data_erp, tipo_data_erp, valor_erp, descricao_erp, diferenca_dias = (
                linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"],
                linha_erp["Favorecido"], 0
            )
            compensacao_original = linha_erp["Data de Compensação Original"]
            vencimento_original = linha_erp["Vencimento Original"]
        else:
            data_erp, tipo_data_erp, valor_erp, descricao_erp, diferenca_dias = pd.NaT, "", None, None, None
            compensacao_original, vencimento_original = None, None
        linhas.append(_linha_resultado_banco(
            linha_banco, STATUS_REVISAO_MANUAL, OBS_DUPLICIDADE_INSUFICIENTE, TIPO_REVISAO_MANUAL,
            data_erp, tipo_data_erp, valor_erp, descricao_erp, diferenca_dias, motivo_revisao=motivo,
            compensacao_original=compensacao_original, vencimento_original=vencimento_original,par_id=par_id_revisao_unico,
        ))

    return linhas, indices_erp_adiados


def _resolver_correspondencias_exatas(
    df_erp: pd.DataFrame, df_banco: pd.DataFrame, e_candidato_lote_erp=None
) -> tuple[list, set, set]:
    """Fase 1: casa lançamentos com mesmo valor absoluto e mesma data exata.

    Mudança 2026-07-10 (ver docs/HISTORICO_DECISOES.md): mesmo um par único (1
    ERP x 1 Banco, sem nenhuma ambiguidade) só concilia direto por "Valor e
    data" quando o ERP NÃO é de um tipo de lote NET EMP (Salário/Folha,
    Férias, Rescisão, 13º). Para esses tipos, valor+data sozinhos não bastam —
    exige também nome/favorecido/descrição forte compatível (`_nome_compativel`).
    Sem esse sinal, o lançamento não é "roubado" do lote por uma coincidência
    pura: fica disponível para a etapa de lote (quando há um lote bancário
    claro do mesmo tipo na mesma data exata, via `e_candidato_lote_erp`) ou vai
    para Revisão Manual com motivo `MOTIVO_REMUNERACAO_SEM_NOME`.

    `e_candidato_lote_erp`, quando informado, também é repassado a
    `_resolver_grupo_ambiguo` para adiar (em vez de finalizar como Revisão
    Manual) um lançamento ERP de lote NET EMP sem sinal seguro em grupos
    ambíguos — ele não entra em `resolvidos_erp` e continua disponível para a
    etapa de lote.
    """
    contagem_erp = df_erp.groupby("_chave_exata").size().to_dict()
    contagem_banco = df_banco.groupby("_chave_exata").size().to_dict()
    chaves_em_comum = set(contagem_erp) & set(contagem_banco)

    linhas, resolvidos_erp, resolvidos_banco = [], set(), set()

    for chave in chaves_em_comum:
        indices_erp = df_erp.index[df_erp["_chave_exata"] == chave].tolist()
        indices_banco = df_banco.index[df_banco["_chave_exata"] == chave].tolist()

        if len(indices_erp) == 1 and len(indices_banco) == 1:
            i, j = indices_erp[0], indices_banco[0]
            linha_erp, linha_banco = df_erp.loc[i], df_banco.loc[j]

            categoria = linha_erp["Categoria"] if "Categoria" in df_erp.columns else ""
            e_tipo_lote = _classificar_tipo_lote(linha_erp["Favorecido"], categoria) is not None
            nome_ok = _nome_compativel(linha_erp["Favorecido"], linha_banco["Favorecido"])

            if e_tipo_lote and not nome_ok:
                if e_candidato_lote_erp is not None and e_candidato_lote_erp(i):
                    # Adiado: existe lote bancário claro do mesmo tipo na mesma
                    # data exata — só o banco (não-lote) fica finalizado aqui.
                    resolvidos_banco.add(j)
                    linhas.append(_linha_resultado_banco(
                        linha_banco, STATUS_REVISAO_MANUAL, OBS_REMUNERACAO_SEM_NOME, TIPO_REVISAO_MANUAL,
                        linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
                        motivo_revisao=MOTIVO_REMUNERACAO_SEM_NOME,
                        compensacao_original=linha_erp["Data de Compensação Original"],
                        vencimento_original=linha_erp["Vencimento Original"],
                    ))
                else:
                    resolvidos_erp.add(i)
                    resolvidos_banco.add(j)
                    linhas.append(_linha_resultado_erp(
                        linha_erp, STATUS_REVISAO_MANUAL, OBS_REMUNERACAO_SEM_NOME, TIPO_REVISAO_MANUAL,
                        linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0,
                        motivo_revisao=MOTIVO_REMUNERACAO_SEM_NOME,
                    ))
                    linhas.append(_linha_resultado_banco(
                        linha_banco, STATUS_REVISAO_MANUAL, OBS_REMUNERACAO_SEM_NOME, TIPO_REVISAO_MANUAL,
                        linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
                        motivo_revisao=MOTIVO_REMUNERACAO_SEM_NOME,
                        compensacao_original=linha_erp["Data de Compensação Original"],
                        vencimento_original=linha_erp["Vencimento Original"],
                    ))
                continue

            tipo_conciliacao = TIPO_VALOR_DATA_NOME if e_tipo_lote else TIPO_VALOR_E_DATA
            resolvidos_erp.add(i)
            resolvidos_banco.add(j)
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_CONCILIADO, "", tipo_conciliacao,
                linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0, par_id=(i, j),
            ))
            linhas.append(_linha_resultado_banco(
                linha_banco, STATUS_CONCILIADO, "", tipo_conciliacao,
                linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0, par_id=(i, j),
                compensacao_original=linha_erp["Data de Compensação Original"],
                vencimento_original=linha_erp["Vencimento Original"],
            ))
            continue

        linhas_grupo, indices_erp_adiados = _resolver_grupo_ambiguo(
            indices_erp, indices_banco, df_erp, df_banco, e_candidato_lote_erp
        )
        linhas.extend(linhas_grupo)
        resolvidos_erp.update(set(indices_erp) - set(indices_erp_adiados))
        resolvidos_banco.update(indices_banco)

    return linhas, resolvidos_erp, resolvidos_banco


def _mapear_compatibilidade_tolerancia(grupo_erp: pd.DataFrame, grupo_banco: pd.DataFrame) -> tuple[dict, dict]:
    """Mapeia, dentro de um mesmo valor absoluto, quais linhas ERP/Banco estão a até
    `TOLERANCIA_DIAS_INDIVIDUAL` dia(s) de distância (usado só para pagamentos
    individuais que sobraram sem par exato — lote NET EMP nunca usa tolerância
    de data, ver `_resolver_correspondencias_por_tolerancia` e `_resolver_lote_net_empr`)."""
    compat_erp = {i: [] for i in grupo_erp.index}
    compat_banco = {j: [] for j in grupo_banco.index}

    for i, linha_erp in grupo_erp.iterrows():
        data_erp = linha_erp["Data ERP Usada"]
        if pd.isna(data_erp):
            continue
        for j, linha_banco in grupo_banco.iterrows():
            data_banco = linha_banco["Data"]
            if pd.isna(data_banco):
                continue
            if abs((data_erp - data_banco).days) <= TOLERANCIA_DIAS_INDIVIDUAL:
                compat_erp[i].append(j)
                compat_banco[j].append(i)

    return compat_erp, compat_banco


def _resolver_correspondencias_por_tolerancia(
    df_erp: pd.DataFrame, df_banco: pd.DataFrame, resolvidos_erp: set, resolvidos_banco: set,
    e_tipo_lote_erp=None,
) -> tuple[list, list, list]:
    """Fase 2: para o que não teve par exato, tenta casar dentro da tolerância de
    `TOLERANCIA_DIAS_INDIVIDUAL` dia(s) — só pagamentos individuais (Mudança
    2026-07-10, ver docs/HISTORICO_DECISOES.md).

    Lote NET EMP (Salário/Folha, Férias, Rescisão, 13º) nunca usa tolerância de
    data: um lançamento ERP desse tipo (`e_tipo_lote_erp`) é sempre desviado
    para `indices_erp_sem_par`, sem tentar nenhum par por proximidade — fica
    pendente para a etapa de lote exigir Data Banco = Data ERP Usada exata.

    Regra revisada em 2026-07-10-c (ver docs/HISTORICO_DECISOES.md): quando há
    mais de um candidato ERP/Banco do mesmo valor dentro da janela de
    tolerância (ex.: um grupo de "Distribuição de Lucros" para várias pessoas,
    todas no mesmo valor e datas próximas), o desempate agora usa o mesmo
    algoritmo de pareamento por nome mutuamente único do grupo de data exata
    (`_desempatar_por_nome`, restrito aos pares dentro da tolerância de data) —
    em vez de olhar ingenuamente só o primeiro candidato da lista. Isso evita
    tanto falsos "Revisão Manual" em massa quanto combinações cruzadas
    incorretas exportadas no resultado.

    Retorna (linhas_finalizadas, índices_erp_ainda_sem_par, índices_banco_ainda_sem_par):
    o que não tem nenhum candidato mesmo com tolerância NÃO é finalizado aqui — fica
    pendente para a fase de lote NET EMPR antes de virar "Não encontrado no
    banco"/"Somente banco" definitivamente.
    """
    pendentes_erp = df_erp.loc[~df_erp.index.isin(resolvidos_erp)]
    pendentes_banco = df_banco.loc[~df_banco.index.isin(resolvidos_banco)]

    linhas = []
    indices_erp_sem_par, indices_banco_sem_par = [], []
    valores = set(pendentes_erp["_valor_abs"]) | set(pendentes_banco["_valor_abs"])

    for valor in valores:
        grupo_erp_completo = pendentes_erp[pendentes_erp["_valor_abs"] == valor]
        grupo_banco = pendentes_banco[pendentes_banco["_valor_abs"] == valor]

        indices_erp_lote = [
            i for i in grupo_erp_completo.index if e_tipo_lote_erp is not None and e_tipo_lote_erp(i)
        ]
        indices_erp_sem_par.extend(indices_erp_lote)
        grupo_erp = grupo_erp_completo.loc[~grupo_erp_completo.index.isin(indices_erp_lote)]

        compat_erp, compat_banco = _mapear_compatibilidade_tolerancia(grupo_erp, grupo_banco)

        indices_erp_com_candidato = [i for i in grupo_erp.index if compat_erp[i]]
        indices_banco_com_candidato = [j for j in grupo_banco.index if compat_banco[j]]
        indices_erp_sem_par.extend(i for i in grupo_erp.index if not compat_erp[i])
        indices_banco_sem_par.extend(j for j in grupo_banco.index if not compat_banco[j])

        if not indices_erp_com_candidato or not indices_banco_com_candidato:
            continue

        pares_permitidos = {(i, j) for i in indices_erp_com_candidato for j in compat_erp[i]}
        confirmados = _desempatar_por_nome(
            indices_erp_com_candidato, indices_banco_com_candidato, df_erp, df_banco,
            pares_permitidos=pares_permitidos,
        )

        for i, j in confirmados.items():
            linha_erp, linha_banco = df_erp.loc[i], df_banco.loc[j]
            diferenca_dias = abs((linha_erp["Data ERP Usada"] - linha_banco["Data"]).days)
            obs = f"Conciliado por tolerância de {diferenca_dias} dia(s), nome/descrição compatível"
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_CONCILIADO, obs, TIPO_VALOR_DATA_TOLERANCIA,
                linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], diferenca_dias,
                par_id=(i, j),
            ))
            linhas.append(_linha_resultado_banco(
                linha_banco, STATUS_CONCILIADO, obs, TIPO_VALOR_DATA_TOLERANCIA,
                linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"],
                diferenca_dias, compensacao_original=linha_erp["Data de Compensação Original"],
                vencimento_original=linha_erp["Vencimento Original"], par_id=(i, j),
            ))

        restantes_erp = [i for i in indices_erp_com_candidato if i not in confirmados]
        restantes_banco = [j for j in indices_banco_com_candidato if j not in confirmados.values()]

        for i in restantes_erp:
            linha_erp = df_erp.loc[i]
            candidatos = compat_erp[i]
            if len(candidatos) == 1:
                j = candidatos[0]
                linha_banco = df_banco.loc[j]
                diferenca_dias = abs((linha_erp["Data ERP Usada"] - linha_banco["Data"]).days)
                motivo = MOTIVO_TOLERANCIA_SEM_EVIDENCIA
                obs = OBS_TOLERANCIA_SEM_EVIDENCIA
                data_banco, valor_banco, descricao_banco = linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"]
            else:
                diferenca_dias = None
                motivo = MOTIVO_EMPATE_NOME
                obs = (
                    f"{len(candidatos)} lançamento(s) do banco compatível(is) dentro da tolerância de "
                    f"{TOLERANCIA_DIAS_INDIVIDUAL} dia(s), sem par mutuamente único por nome"
                )
                data_banco, valor_banco, descricao_banco = pd.NaT, None, None

            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_REVISAO_MANUAL, obs, TIPO_REVISAO_MANUAL,
                data_banco, valor_banco, descricao_banco, diferenca_dias, motivo_revisao=motivo,
            ))

        for j in restantes_banco:
            linha_banco = df_banco.loc[j]
            candidatos = compat_banco[j]
            if len(candidatos) == 1:
                i = candidatos[0]
                linha_erp = df_erp.loc[i]
                diferenca_dias = abs((linha_erp["Data ERP Usada"] - linha_banco["Data"]).days)
                motivo = MOTIVO_TOLERANCIA_SEM_EVIDENCIA
                obs = OBS_TOLERANCIA_SEM_EVIDENCIA
                data_erp, tipo_data_erp, valor_erp, descricao_erp = (
                    linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"]
                )
                compensacao_original, vencimento_original = (
                    linha_erp["Data de Compensação Original"], linha_erp["Vencimento Original"]
                )
            else:
                diferenca_dias = None
                motivo = MOTIVO_EMPATE_NOME
                obs = (
                    f"{len(candidatos)} lançamento(s) do ERP compatível(is) dentro da tolerância de "
                    f"{TOLERANCIA_DIAS_INDIVIDUAL} dia(s), sem par mutuamente único por nome"
                )
                data_erp, tipo_data_erp, valor_erp, descricao_erp = pd.NaT, "", None, None
                compensacao_original, vencimento_original = None, None

            linhas.append(_linha_resultado_banco(
                linha_banco, STATUS_REVISAO_MANUAL, obs, TIPO_REVISAO_MANUAL,
                data_erp, tipo_data_erp, valor_erp, descricao_erp, diferenca_dias, motivo_revisao=motivo,
                compensacao_original=compensacao_original, vencimento_original=vencimento_original,
            ))

    return linhas, indices_erp_sem_par, indices_banco_sem_par


def _e_candidato_lote_banco(favorecido) -> bool:
    """Entra na regra de lote só quem tem marcador NET EMP/EMPR/EMPRESA **e** um
    termo de tipo claro (salário, férias, rescisão, folha ou 13º) — nunca um
    NET EMPRESA genérico (ex.: "PAG COBRANCA NET EMPRESA") — e nunca quem
    parecer uma transferência individual (PIX/TED/DOC/transferência)."""
    if contem_alguma_palavra(favorecido, PALAVRAS_EXCLUSAO_LOTE_BANCO):
        return False
    if not contem_alguma_palavra(favorecido, PALAVRAS_MARCADOR_LOTE_BANCO):
        return False
    return contem_alguma_palavra(favorecido, PALAVRAS_TIPO_LOTE_CLARO)


def _classificar_tipo_lote(texto, categoria="") -> str | None:
    """Classifica um texto (descrição do banco, ou descrição+categoria do ERP) num
    tipo de lote específico, nesta ordem de prioridade. Retorna None quando não
    bate em nenhum tipo específico (candidato só ao lote genérico).

    Regra 2026-07-10-d: nunca classifica como lote quando o texto contém uma
    palavra de exclusão (`PALAVRAS_EXCLUSAO_TIPO_LOTE_ERP`, hoje só "FGTS") —
    tem prioridade sobre qualquer termo de tipo que também apareça no mesmo texto.
    """
    combinado = f"{texto} {categoria}"
    if contem_alguma_palavra(combinado, PALAVRAS_EXCLUSAO_TIPO_LOTE_ERP):
        return None
    if contem_alguma_palavra(combinado, PALAVRAS_TIPO_SALARIO_FOLHA):
        return TIPO_LOTE_SALARIO_FOLHA
    if contem_alguma_palavra(combinado, PALAVRAS_TIPO_FERIAS):
        return TIPO_LOTE_FERIAS
    if contem_alguma_palavra(combinado, PALAVRAS_TIPO_RESCISAO):
        return TIPO_LOTE_RESCISAO
    if contem_alguma_palavra(combinado, PALAVRAS_TIPO_DECIMO):
        return TIPO_LOTE_DECIMO_TERCEIRO
    return None


def _descricao_grupo_banco(df_banco: pd.DataFrame, lista_banco: list, tipo: str) -> tuple:
    """Retorna (data, valor, descrição) representando o lado banco de um lote —
    ou o próprio lançamento quando há só 1, ou um resumo agregado quando há vários."""
    if len(lista_banco) == 1:
        linha = df_banco.loc[lista_banco[0]]
        return linha["Data"], linha["Valor"], linha["Favorecido"]
    data = df_banco.at[lista_banco[0], "Data"]
    soma = sum(df_banco.at[j, "Valor"] for j in lista_banco)
    return data, soma, f"Lote {tipo} ({len(lista_banco)} lançamento(s) do banco)"


def _descricao_grupo_erp(df_erp: pd.DataFrame, grupo_erp: list, tipo: str, data_lote) -> tuple:
    """Retorna (data_erp, tipo_data_erp, valor, descrição, compensação original,
    vencimento original) representando o lado ERP de um lote — o próprio
    lançamento quando há só 1, ou um resumo agregado quando há vários (ou zero)."""
    if len(grupo_erp) == 1:
        linha = df_erp.loc[grupo_erp[0]]
        return (
            linha["Data ERP Usada"], linha["Tipo Data ERP"], linha["Valor"], linha["Favorecido"],
            linha["Data de Compensação Original"], linha["Vencimento Original"],
        )
    soma = sum(df_erp.at[i, "Valor"] for i in grupo_erp)
    descricao = f"Lote {tipo} ({len(grupo_erp)} lançamento(s) do ERP)" if grupo_erp else "Nenhum candidato do ERP"
    return data_lote, "Lote", (soma if grupo_erp else None), descricao, None, None


def _subconjuntos_com_soma(itens: list) -> list:
    """Gera (soma, tupla_de_índices) de cada subconjunto de `itens` (lista de
    (índice, valor_centavos)), incluindo o vazio. Usado só dentro de
    `_buscar_combinacao_unica_centavos` (meet-in-the-middle)."""
    resultado = [(0, ())]
    for indice, valor in itens:
        resultado = resultado + [(soma + valor, indices + (indice,)) for soma, indices in resultado]
    return resultado


# Nenhuma busca de combinação é tentada acima deste número de candidatos (seria
# lento e pesado demais em memória mesmo com meet-in-the-middle) — trata como
# "grupo grande demais" em vez de arriscar uma busca incompleta/travar.
LIMITE_ITENS_COMBINACAO_LOTE = 40


def _buscar_combinacao_unica_centavos(itens: list, alvo_centavos: int, limite_itens: int = LIMITE_ITENS_COMBINACAO_LOTE):
    """Etapa B (regra 3 do CLAUDE.md): procura um subconjunto de `itens` (lista
    de (índice, valor_centavos), já em centavos inteiros para evitar erro de
    arredondamento) cuja soma seja exatamente `alvo_centavos`.

    Usa meet-in-the-middle (divide os itens em duas metades e enumera todos os
    subconjuntos de cada uma) — rápido e seguro até `limite_itens` lançamentos;
    acima disso, retorna "GRUPO_GRANDE" em vez de arriscar uma busca incompleta.

    Retorna (resultado, combinação):
    - ("UNICA", [índices]) quando existe exatamente 1 combinação exata;
    - ("NENHUMA", None) quando não existe nenhuma;
    - ("MULTIPLAS", None) quando existem 2 ou mais (ambíguo — nunca adivinha);
    - ("GRUPO_GRANDE", None) quando o grupo é grande demais para buscar com segurança.
    """
    if alvo_centavos <= 0 or not itens:
        return "NENHUMA", None
    if len(itens) > limite_itens:
        return "GRUPO_GRANDE", None

    metade = len(itens) // 2
    subs1 = _subconjuntos_com_soma(itens[:metade])
    subs2 = _subconjuntos_com_soma(itens[metade:])

    mapa2: dict = defaultdict(list)
    for soma, indices in subs2:
        mapa2[soma].append(indices)

    combinacoes_encontradas = []
    for soma1, indices1 in subs1:
        for indices2 in mapa2.get(alvo_centavos - soma1, []):
            if not indices1 and not indices2:
                continue  # combinação vazia não conta como lote
            combinacoes_encontradas.append(indices1 + indices2)
            if len(combinacoes_encontradas) > 1:
                return "MULTIPLAS", None

    if len(combinacoes_encontradas) == 1:
        return "UNICA", list(combinacoes_encontradas[0])
    return "NENHUMA", None


# Vocabulário genérico de lote NET EMP (marcadores + termos de tipo) — usado só
# para decidir se o banco trouxe algo além disso (nome, CPF, documento). Ver
# _banco_tem_identificador_individual e a etapa C do CLAUDE.md.
_TOKENS_VOCABULARIO_LOTE_BANCO = {
    "PGTO", "PAGTO", "VIA", "NET", "EMP", "EMPR", "EMPRESA",
    "SALARIO", "FOLHA", "PRO", "LABORE", "FERIAS", "RESCISAO", "13", "DECIMO",
}


def _banco_tem_identificador_individual(favorecido) -> bool:
    """Etapa C (regra 3 do CLAUDE.md): só faz sentido tentar nome/descrição
    quando a descrição do banco tem algo além do vocabulário genérico do lote
    (nome, CPF, documento, identificador individual) — "PGTO SALARIO VIA NET
    EMP" sozinho não tem nada disso."""
    termos = extrair_termos_relevantes(favorecido)
    return bool(termos - _TOKENS_VOCABULARIO_LOTE_BANCO)


def _resolver_lote_net_empr(
    df_erp: pd.DataFrame, df_banco: pd.DataFrame, indices_erp_pendentes: list, indices_banco_lote_reservados: list,
    logger: logging.Logger,
) -> tuple[list, set, set]:
    """Fase 3 (ordem obrigatória do CLAUDE.md, passo 11): `indices_banco_lote_reservados`
    já foi separado ANTES da conciliação individual (ver conciliar()) — lançamentos
    NET EMP/EMPR nunca são conciliados por valor e data isoladamente.

    Para cada (Data, Tipo Lote), tenta fechar automaticamente nesta ordem
    (sempre em centavos inteiros, nunca ponto flutuante — nunca adivinha):

    A) total direto: soma TODOS os candidatos do ERP contra a soma de TODOS os
       lançamentos do banco do grupo — bate exatamente, concilia tudo.
    B) combinação única: se o total do ERP for maior que o do banco, procura
       um subconjunto dos candidatos cuja soma feche exatamente o total do
       banco — só concilia se existir EXATAMENTE UMA combinação possível.
    C) nome/descrição: só quando o banco do grupo traz identificador
       individual (nome, CPF, documento) além do vocabulário genérico do
       lote — tenta parear cada lançamento do banco com um candidato do ERP
       por termos mutuamente únicos; só aceita se resolver TODOS os
       lançamentos do banco do grupo.

    Se nenhuma etapa fechar, todos ficam em Revisão Manual com o motivo
    específico (qual etapa falhou e por quê) no Motivo Revisão. Nunca resume
    em uma única linha: cada lançamento (ERP e Banco) continua aparecendo
    individualmente no Resultado.xlsx.
    """
    candidatos_banco = []
    for j in indices_banco_lote_reservados:
        favorecido = df_banco.at[j, "Favorecido"]
        tipo = _classificar_tipo_lote(favorecido) or TIPO_LOTE_GENERICO
        candidatos_banco.append((j, tipo))

    linhas: list = []
    resolvidos_erp, resolvidos_banco = set(), set()

    logger.info(f"Lançamentos NET EMP/EMPR reservados para lote (nunca individuais): {len(candidatos_banco)}")

    if not candidatos_banco:
        return linhas, resolvidos_erp, resolvidos_banco

    # Cada lançamento do ERP é classificado num único tipo específico; o que
    # não bate em nenhum tipo específico só entra no balde genérico — evita
    # "roubar" candidatos de um tipo mais específico. Classifica TODO o ERP
    # (não só o pendente) para o diagnóstico "antes da conciliação individual"
    # (regra 9 do pedido de reordenação — ver docs/HISTORICO_DECISOES.md,
    # 2026-07-10); o balde "pendente" (subconjunto do que sobrou depois da
    # conciliação individual) é o que de fato tenta fechar o lote.
    baldes_erp_especificos_todos: dict = {
        TIPO_LOTE_SALARIO_FOLHA: [], TIPO_LOTE_FERIAS: [], TIPO_LOTE_RESCISAO: [], TIPO_LOTE_DECIMO_TERCEIRO: [],
    }
    candidatos_erp_genericos_todos = []
    for i in df_erp.index:
        favorecido = df_erp.at[i, "Favorecido"]
        categoria = df_erp.at[i, "Categoria"] if "Categoria" in df_erp.columns else ""
        tipo = _classificar_tipo_lote(favorecido, categoria)
        if tipo:
            baldes_erp_especificos_todos[tipo].append(i)
        else:
            candidatos_erp_genericos_todos.append(i)

    pendentes_set = set(indices_erp_pendentes)
    baldes_erp_especificos = {
        tipo: [i for i in lista if i in pendentes_set] for tipo, lista in baldes_erp_especificos_todos.items()
    }
    candidatos_erp_genericos = [i for i in candidatos_erp_genericos_todos if i in pendentes_set]

    grupos_banco: dict = {}
    for j, tipo in candidatos_banco:
        data = df_banco.at[j, "Data"]
        grupos_banco.setdefault((data, tipo), []).append(j)

    contadores_id: dict = {}
    contagem_total_direto = 0
    contagem_combinacao_unica = 0
    contagem_por_nome = 0
    contagem_revisao = 0

    for (data, tipo), lista_banco in sorted(grupos_banco.items(), key=lambda item: (item[0][0], item[0][1])):
        pool_erp_todos = baldes_erp_especificos_todos.get(tipo, candidatos_erp_genericos_todos)
        grupo_erp_original = [i for i in pool_erp_todos if df_erp.at[i, "Data ERP Usada"] == data]

        pool_erp = baldes_erp_especificos.get(tipo, candidatos_erp_genericos)
        # Mudança 2026-07-10: lote NET EMP não usa tolerância de data — só
        # candidatos com a mesma Data ERP Usada exata do lote bancário.
        grupo_erp = [i for i in pool_erp if df_erp.at[i, "Data ERP Usada"] == data]

        quantidade_erp_antes_individual = len(grupo_erp_original)
        quantidade_erp_conciliados_antes_lote = quantidade_erp_antes_individual - len(grupo_erp)

        soma_banco_centavos = sum(round(abs(df_banco.at[j, "Valor"]) * 100) for j in lista_banco)
        soma_erp_centavos = sum(round(df_erp.at[i, "Valor"] * 100) for i in grupo_erp)
        soma_banco = soma_banco_centavos / 100
        soma_erp = soma_erp_centavos / 100
        diferenca = round(soma_erp - soma_banco, 2)
        bateu = grupo_erp and soma_erp_centavos == soma_banco_centavos

        logger.info(
            f"Lote NET EMP | Data: {data} | Tipo: {tipo} | Banco: {len(lista_banco)} lançamento(s) = "
            f"R$ {soma_banco:.2f} | ERP candidato: {len(grupo_erp)} lançamento(s) = R$ {soma_erp:.2f} | "
            f"Diferença: R$ {diferenca:.2f}"
        )
        for j in lista_banco:
            logger.info(f"    Banco NET EMP: {df_banco.at[j, 'Data']} | R$ {df_banco.at[j, 'Valor']:.2f} | {df_banco.at[j, 'Favorecido']}")
        for i in grupo_erp:
            logger.info(f"    ERP candidato: {df_erp.at[i, 'Data ERP Usada']} | R$ {df_erp.at[i, 'Valor']:.2f} | {df_erp.at[i, 'Favorecido']}")

        chave_id = (tipo, data)
        contadores_id[chave_id] = contadores_id.get(chave_id, 0) + 1
        id_grupo = f"{PREFIXO_ID_LOTE[tipo]}-{data.isoformat()}-{contadores_id[chave_id]:03d}"

        excluidos: list = []  # [(índice ERP, observação)] — candidatos fora do subconjunto que fechou o lote
        detalhes = (
            f"total ERP candidato R$ {soma_erp:.2f} ({len(grupo_erp)} lançamento(s)) x total Banco NET EMP "
            f"R$ {soma_banco:.2f} ({len(lista_banco)} lançamento(s)); diferença R$ {diferenca:.2f}"
        )

        # Etapa A: total direto.
        if bateu:
            resultado_total_direto = "Bateu exatamente"
            resultado_combinacao = "Não tentado (total direto já bateu)"
            resultado_nome = "Não tentado (total direto já bateu)"
            status_lote, motivo = STATUS_CONCILIADO, None
            obs = OBS_LOTE_CONSOLIDADO
            tipo_conciliacao = TIPO_CONCILIACAO_LOTE_CONSOLIDADO
            id_lote = id_grupo
            grupo_erp_final = grupo_erp
            contagem_total_direto += 1
            logger.info(f"    -> CONCILIADO por total direto ({id_grupo})")

        elif not grupo_erp or soma_erp_centavos <= soma_banco_centavos:
            # ERP não alcança o banco (menor ou igual sem bater, ou nenhum
            # candidato) — nenhuma combinação nem nome resolve isso. Quando não
            # há candidato NA DATA EXATA mas existem candidatos do mesmo tipo
            # em outra data (Mudança 2026-07-10: lote não usa tolerância), o
            # motivo é divergência de data, não "ERP menor que banco".
            if not grupo_erp and pool_erp_todos:
                resultado_total_direto = "Não tentável (nenhum candidato do ERP na mesma data exata)"
                motivo_prefixo = MOTIVO_LOTE_DIVERGENCIA_DATA
            elif not grupo_erp:
                resultado_total_direto = "Não tentável (nenhum candidato do ERP)"
                motivo_prefixo = MOTIVO_LOTE_ERP_MENOR_QUE_BANCO
            else:
                resultado_total_direto = "Não bateu (ERP menor que banco)"
                motivo_prefixo = MOTIVO_LOTE_ERP_MENOR_QUE_BANCO
            resultado_combinacao = "Não tentável (ERP menor ou igual ao banco)"
            resultado_nome = "Não tentável (ERP menor ou igual ao banco)"
            status_lote = STATUS_REVISAO_MANUAL
            motivo = f"{motivo_prefixo}: {detalhes}"
            obs = motivo
            tipo_conciliacao = TIPO_REVISAO_MANUAL
            id_lote = None
            grupo_erp_final = grupo_erp
            contagem_revisao += 1
            logger.info(f"    -> REVISÃO MANUAL: {motivo}")

        else:
            # ERP maior que banco: Etapa B (combinação única), depois Etapa C
            # (nome/descrição, só se o banco trouxer identificador individual).
            resultado_total_direto = "Não bateu (ERP maior que banco)"
            itens_centavos = [(i, round(df_erp.at[i, "Valor"] * 100)) for i in grupo_erp]
            resultado_b, combinacao = _buscar_combinacao_unica_centavos(itens_centavos, soma_banco_centavos)

            if resultado_b == "UNICA":
                resultado_combinacao = "Combinação única encontrada"
                resultado_nome = "Não tentado (combinação única já resolveu)"
                status_lote, motivo = STATUS_CONCILIADO, None
                obs = OBS_LOTE_COMBINACAO_UNICA
                tipo_conciliacao = TIPO_LOTE_COMBINACAO_UNICA
                id_lote = id_grupo
                grupo_erp_final = combinacao
                excluidos = [(i, OBS_LOTE_EXCLUIDO_COMBINACAO) for i in grupo_erp if i not in set(combinacao)]
                contagem_combinacao_unica += 1
                logger.info(f"    -> CONCILIADO por combinação única ({id_grupo})")
            else:
                resultado_combinacao = {
                    "MULTIPLAS": "Múltiplas combinações possíveis",
                    "NENHUMA": "Nenhuma combinação exata encontrada",
                    "GRUPO_GRANDE": "Grupo grande demais para busca automática",
                }[resultado_b]

                tem_identificador = all(_banco_tem_identificador_individual(df_banco.at[j, "Favorecido"]) for j in lista_banco)
                pares_por_nome = _desempatar_por_nome(grupo_erp, lista_banco, df_erp, df_banco) if tem_identificador else {}

                if tem_identificador and len(pares_por_nome) == len(lista_banco):
                    resultado_nome = "Identificado por nome/descrição"
                    status_lote, motivo = STATUS_CONCILIADO, None
                    obs = OBS_LOTE_POR_NOME
                    tipo_conciliacao = TIPO_LOTE_POR_NOME
                    id_lote = id_grupo
                    grupo_erp_final = list(pares_por_nome.keys())
                    excluidos = [(i, OBS_LOTE_EXCLUIDO_NOME) for i in grupo_erp if i not in pares_por_nome]
                    contagem_por_nome += 1
                    logger.info(f"    -> CONCILIADO por nome/descrição ({id_grupo})")
                else:
                    resultado_nome = (
                        "Tentado, não resolveu com segurança" if tem_identificador
                        else "Não tentado (banco genérico, sem nome/identificador)"
                    )
                    motivo_prefixo = (
                        MOTIVO_LOTE_MULTIPLAS_COMBINACOES if resultado_b == "MULTIPLAS"
                        else MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO if not tem_identificador
                        else MOTIVO_LOTE_NENHUMA_COMBINACAO
                    )
                    status_lote = STATUS_REVISAO_MANUAL
                    motivo = f"{motivo_prefixo}: {detalhes}"
                    obs = motivo
                    tipo_conciliacao = TIPO_REVISAO_MANUAL
                    id_lote = None
                    grupo_erp_final = grupo_erp
                    contagem_revisao += 1
                    logger.info(f"    -> REVISÃO MANUAL: {motivo}")

        # Um lote só vira um par 1-para-1 "de verdade" (mergeável numa única
        # linha pela Regra 1) quando fecha com exatamente 1 lançamento do ERP
        # e 1 do banco; grupos com mais de um lançamento de qualquer lado
        # continuam com uma linha por lançamento — nunca resumidos.
        par_id_lote = (
            (grupo_erp_final[0], lista_banco[0])
            if status_lote == STATUS_CONCILIADO and len(grupo_erp_final) == 1 and len(lista_banco) == 1
            else None
        )

        data_banco_grp, valor_banco_grp, descricao_banco_grp = _descricao_grupo_banco(df_banco, lista_banco, tipo)
        for i in grupo_erp_final:
            linha_erp = df_erp.loc[i]
            linhas.append(_linha_resultado_erp(
                linha_erp, status_lote, obs, tipo_conciliacao,
                data_banco_grp, valor_banco_grp, descricao_banco_grp, 0, id_lote, motivo, par_id=par_id_lote,
            ))

        data_erp_grp, tipo_data_erp_grp, valor_erp_grp, descricao_erp_grp, comp_orig, venc_orig = (
            _descricao_grupo_erp(df_erp, grupo_erp_final, tipo, data)
        )
        for j in lista_banco:
            linha_banco = df_banco.loc[j]
            linhas.append(_linha_resultado_banco(
                linha_banco, status_lote, obs, tipo_conciliacao,
                data_erp_grp, tipo_data_erp_grp, valor_erp_grp, descricao_erp_grp, 0, id_lote, motivo,
                compensacao_original=comp_orig, vencimento_original=venc_orig, par_id=par_id_lote,
            ))

        # Candidatos do ERP que não fazem parte do subconjunto/pareamento que
        # fechou o lote (só existe quando o lote fechou por combinação única
        # ou por nome) — a evidência exata prova que não pertencem a este
        # lote, então viram "Não encontrado no banco".
        for i, obs_exclusao in excluidos:
            linha_erp = df_erp.loc[i]
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_NAO_ENCONTRADO_BANCO, obs_exclusao, TIPO_NAO_ENCONTRADO_BANCO,
                pd.NaT, None, None, None, motivo_nao_conciliado=obs_exclusao,
            ))

        resolvidos_erp.update(grupo_erp)
        resolvidos_banco.update(lista_banco)

        # Regra 2 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): não existe
        # mais aba própria de diagnóstico de lote — o detalhe completo de cada
        # grupo (candidatos antes/depois da conciliação individual, resultado
        # de cada etapa) fica preservado aqui no log; o resumo essencial
        # (status final e motivo, quando não fechou) já vai em cada linha do
        # Resultado via Observações/Motivo Revisão.
        logger.info(
            f"    Diagnóstico lote {id_grupo}: {quantidade_erp_antes_individual} candidato(s) ERP antes da "
            f"conciliação individual, {quantidade_erp_conciliados_antes_lote} já conciliado(s) antes do lote | "
            f"total direto: {resultado_total_direto} | combinação única: {resultado_combinacao} | "
            f"nome/descrição: {resultado_nome} | status final: {status_lote}"
        )

    # Mudança 2026-07-10: lote NET EMP não usa tolerância de data — um
    # candidato do ERP de um tipo com lote bancário claro nesta execução, mas
    # cuja Data ERP Usada não bate exatamente com nenhuma data desse tipo,
    # nunca pode cair silenciosamente em "Não encontrado no banco": fica em
    # Revisão Manual com o motivo específico de divergência de data.
    contagem_divergencia_data = 0
    tipos_com_lote_banco = {tipo for (_, tipo) in grupos_banco}
    for tipo in tipos_com_lote_banco:
        for i in baldes_erp_especificos.get(tipo, []):
            if i in resolvidos_erp:
                continue
            linha_erp = df_erp.loc[i]
            motivo = (
                f"{MOTIVO_LOTE_DIVERGENCIA_DATA}: Data ERP Usada {linha_erp['Data ERP Usada']} não coincide "
                f"com nenhuma data de lote {tipo} nesta execução"
            )
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_REVISAO_MANUAL, motivo, TIPO_REVISAO_MANUAL,
                pd.NaT, None, None, None, motivo_revisao=motivo,
            ))
            resolvidos_erp.add(i)
            contagem_divergencia_data += 1

    logger.info(f"Grupos de lote NET EMP avaliados (data + tipo): {len(grupos_banco)}")
    logger.info(f"Lotes NET EMP conciliados por total direto: {contagem_total_direto}")
    logger.info(f"Lotes NET EMP conciliados por combinação exata única: {contagem_combinacao_unica}")
    logger.info(f"Lotes NET EMP conciliados por nome/descrição: {contagem_por_nome}")
    logger.info(f"Lotes NET EMP em Revisão Manual: {contagem_revisao}")
    logger.info(f"ERP de lote com divergência de data (Revisão Manual): {contagem_divergencia_data}")

    return linhas, resolvidos_erp, resolvidos_banco


def _verificar_possiveis_pares_nao_encontrados(
    df_erp: pd.DataFrame, df_banco: pd.DataFrame, indices_erp_finais: list, indices_banco_finais: list,
    logger: logging.Logger,
) -> tuple[list, set, set]:
    """Regra revisada em 2026-07-10 (ver docs/HISTORICO_DECISOES.md): antes de
    finalizar um ERP como "Não encontrado no banco", verifica se existe um
    possível par no banco (usado ou não) por valor absoluto + data + nome/
    descrição — só roda sobre o que sobrou depois de TODAS as fases
    principais (individual, tolerância, lote), para nunca interferir nelas.

    Regra revisada em 2026-07-10-d (ver docs/HISTORICO_DECISOES.md): quando o
    candidato é único por valor+data dos dois lados (mutuamente único) e ainda
    está pendente, concilia automaticamente **mesmo sem nome/descrição
    compatível** — não existe ambiguidade operacional quando valor e data já
    bastam para identificar o par sem risco de escolha errada. O nome, quando
    também bate, só enriquece o Tipo Conciliação ("Valor, data e nome" em vez
    de "Valor e data"); deixou de ser exigido para conciliar aqui. Continua
    nunca forçando conciliação quando há risco real: 2+ candidatos por
    valor+data (de qualquer lado) ou banco já consumido por outro lançamento
    sempre viram Revisão Manual, nunca escolhidos ao acaso.

    Regra 2 (2026-07-10-b, ver docs/HISTORICO_DECISOES.md): esta função agora
    finaliza TODOS os ERP de `indices_erp_finais` — inclusive os que
    permanecem "Não encontrado no banco" — preenchendo diretamente nas
    colunas da própria linha ("Motivo Não Conciliado", "Possível Data/Valor/
    Descrição Banco", "Status do Possível Banco") o que antes só existia numa
    aba separada de diagnóstico. Não há mais aba/DataFrame de diagnóstico.

    Retorna (linhas, erp_reclassificados, banco_reclassificados): `linhas` já
    inclui a finalização completa (Conciliado, Revisão Manual ou Não
    encontrado no banco) de cada ERP desta lista; `erp_reclassificados` cobre
    100% de `indices_erp_finais` (nada mais precisa passar por
    `_finalizar_sem_correspondencia` do lado ERP); `banco_reclassificados`
    sai de `indices_banco_finais` antes de `_finalizar_sem_correspondencia`.
    """
    banco_pendente = set(indices_banco_finais)

    # Pré-computa, para cada ERP, os candidatos do banco por mesmo valor+data
    # (usados ou não) e por mesmo valor+nome em qualquer data — usado tanto
    # para decidir quanto para o diagnóstico.
    candidatos_mesma_data: dict = {}
    for i in indices_erp_finais:
        valor_i = df_erp.at[i, "_valor_abs"]
        data_i = df_erp.at[i, "Data ERP Usada"]
        if pd.isna(data_i):
            candidatos_mesma_data[i] = []
            continue
        candidatos_mesma_data[i] = [
            j for j in df_banco.index
            if df_banco.at[j, "_valor_abs"] == valor_i and df_banco.at[j, "Data"] == data_i
        ]

    # Quantos ERPs desta lista apontam para o mesmo banco ainda pendente, só
    # por valor+data (regra 2026-07-10-d: nome não é mais exigido aqui) —
    # usado para checar unicidade mútua antes de conciliar.
    apontamentos_banco: dict = {}
    for i, candidatos in candidatos_mesma_data.items():
        for j in candidatos:
            if j in banco_pendente:
                apontamentos_banco.setdefault(j, []).append(i)

    linhas: list = []
    erp_reclassificados: set = set()
    banco_reclassificados: set = set()
    contagem_conciliados = contagem_revisao = 0

    for i in indices_erp_finais:
        linha_erp = df_erp.loc[i]
        candidatos = candidatos_mesma_data[i]
        status_atual = STATUS_NAO_ENCONTRADO_BANCO
        motivo = None
        banco_ref = None

        if candidatos:
            if len(candidatos) == 1:
                j = candidatos[0]
                banco_ref = j
                if j not in banco_pendente:
                    # Caso F/C do pedido: já foi consumido por outro par —
                    # nunca desfaz a conciliação anterior para "roubar" o banco.
                    motivo = MOTIVO_NAO_ENCONTRADO_BANCO_CONSUMIDO
                    status_atual = STATUS_REVISAO_MANUAL
                elif len(apontamentos_banco.get(j, [])) == 1:
                    # Regra 2026-07-10-d: candidato único por valor+data dos
                    # dois lados, ainda pendente — concilia mesmo sem nome
                    # (não há ambiguidade operacional). Nome, quando compatível,
                    # só enriquece o Tipo Conciliação e a Observação.
                    linha_banco = df_banco.loc[j]
                    nome_ok = _nome_compativel(linha_erp["Favorecido"], linha_banco["Favorecido"])
                    tipo = TIPO_VALOR_DATA_NOME if nome_ok else TIPO_VALOR_E_DATA
                    obs = OBS_RECUPERADO_NAO_ENCONTRADO if nome_ok else OBS_RECUPERADO_VALOR_DATA_UNICOS
                    linhas.append(_linha_resultado_erp(
                        linha_erp, STATUS_CONCILIADO, obs, tipo,
                        linha_banco["Data"], linha_banco["Valor"], linha_banco["Favorecido"], 0, par_id=(i, j),
                    ))
                    linhas.append(_linha_resultado_banco(
                        linha_banco, STATUS_CONCILIADO, obs, tipo,
                        linha_erp["Data ERP Usada"], linha_erp["Tipo Data ERP"], linha_erp["Valor"], linha_erp["Favorecido"], 0,
                        compensacao_original=linha_erp["Data de Compensação Original"],
                        vencimento_original=linha_erp["Vencimento Original"], par_id=(i, j),
                    ))
                    erp_reclassificados.add(i)
                    banco_reclassificados.add(j)
                    status_atual = STATUS_CONCILIADO
                    contagem_conciliados += 1
                    logger.info(f"Recuperado da verificação final de 'Não encontrado no banco': ERP #{i} <-> Banco #{j}")
                else:
                    # Caso C/D/Regra 6 do pedido: o único banco disponível
                    # desse valor+data também é reivindicado por outro ERP —
                    # ambíguo, nunca escolhe um sozinho.
                    motivo = MOTIVO_NAO_ENCONTRADO_MULTIPLOS
                    status_atual = STATUS_REVISAO_MANUAL
            else:
                # 2+ lançamentos do banco com o mesmo valor+data — ambíguo
                # demais para decidir sozinho (Caso C/D/Regra 6 do pedido).
                motivo = MOTIVO_NAO_ENCONTRADO_MULTIPLOS
                status_atual = STATUS_REVISAO_MANUAL
                banco_ref = candidatos[0]
        else:
            # Sem candidato na mesma data: tenta por valor+nome em qualquer data.
            valor_i = df_erp.at[i, "_valor_abs"]
            candidatos_nome = [
                j for j in df_banco.index
                if df_banco.at[j, "_valor_abs"] == valor_i
                and _nome_compativel(linha_erp["Favorecido"], df_banco.at[j, "Favorecido"])
            ]
            if len(candidatos_nome) == 1:
                motivo = MOTIVO_NAO_ENCONTRADO_DIVERGENCIA_DATA
                status_atual = STATUS_REVISAO_MANUAL
                banco_ref = candidatos_nome[0]

        if status_atual == STATUS_CONCILIADO:
            continue

        if banco_ref is not None:
            linha_banco_ref = df_banco.loc[banco_ref]
            status_possivel_banco = (
                "Conciliado nesta verificação" if banco_ref in banco_reclassificados
                else "Pendente (seria Somente banco)" if banco_ref in banco_pendente
                else "Já consumido por outro lançamento"
            )
            possivel_data, possivel_valor, possivel_descricao = (
                linha_banco_ref["Data"], linha_banco_ref["Valor"], linha_banco_ref["Favorecido"]
            )
        else:
            status_possivel_banco, possivel_data, possivel_valor, possivel_descricao = None, pd.NaT, None, None

        if status_atual == STATUS_REVISAO_MANUAL:
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_REVISAO_MANUAL, motivo, TIPO_REVISAO_MANUAL,
                pd.NaT, None, None, None, motivo_revisao=motivo,
                possivel_data_banco=possivel_data, possivel_valor_banco=possivel_valor,
                possivel_descricao_banco=possivel_descricao, status_possivel_banco=status_possivel_banco,
            ))
            contagem_revisao += 1
        else:
            # status_atual == STATUS_NAO_ENCONTRADO_BANCO: nenhuma etapa achou
            # evidência suficiente — permanece "Não encontrado no banco", mas
            # a linha já traz o motivo e o possível candidato (se houver),
            # nunca "sem explicação" (Regra 2, 2026-07-10-b).
            linhas.append(_linha_resultado_erp(
                linha_erp, STATUS_NAO_ENCONTRADO_BANCO, "", TIPO_NAO_ENCONTRADO_BANCO,
                pd.NaT, None, None, None,
                motivo_nao_conciliado=motivo or MOTIVO_NAO_ENCONTRADO_SEM_CANDIDATO,
                possivel_data_banco=possivel_data, possivel_valor_banco=possivel_valor,
                possivel_descricao_banco=possivel_descricao, status_possivel_banco=status_possivel_banco,
            ))

        erp_reclassificados.add(i)

    logger.info(
        f"Verificação final de 'Não encontrado no banco': {len(indices_erp_finais)} ERP avaliados, "
        f"{contagem_conciliados} recuperados como Conciliado, {contagem_revisao} viraram Revisão Manual."
    )

    return linhas, erp_reclassificados, banco_reclassificados


def _finalizar_sem_correspondencia(df_erp: pd.DataFrame, df_banco: pd.DataFrame, indices_erp: list, indices_banco: list) -> list:
    """O que não foi resolvido em nenhuma fase vira definitivamente Não encontrado/Somente banco.

    Depois da Regra 2 (2026-07-10-b), o lado ERP normalmente chega vazio aqui
    — `_verificar_possiveis_pares_nao_encontrados` já finaliza 100% do ERP
    pendente (inclusive o que permanece "Não encontrado no banco", com motivo
    e possível candidato preenchidos na própria linha). Esta função continua
    aceitando `indices_erp` por robustez, mas na prática só sobra o lado Banco.
    """
    linhas = []
    for i in indices_erp:
        linha = df_erp.loc[i]
        linhas.append(_linha_resultado_erp(
            linha, STATUS_NAO_ENCONTRADO_BANCO, "", TIPO_NAO_ENCONTRADO_BANCO, pd.NaT, None, None, None,
            motivo_nao_conciliado=MOTIVO_NAO_ENCONTRADO_SEM_CANDIDATO,
        ))
    for j in indices_banco:
        linha = df_banco.loc[j]
        linhas.append(_linha_resultado_banco(
            linha, STATUS_SOMENTE_BANCO, "", TIPO_SOMENTE_BANCO, pd.NaT, "", None, None, None,
            motivo_nao_conciliado=MOTIVO_SOMENTE_BANCO_SEM_ERP,
        ))
    return linhas


def conciliar(
    df_erp: pd.DataFrame, df_banco: pd.DataFrame, logger: logging.Logger,
    config_ia=None, cliente_ia=None,
) -> pd.DataFrame:
    """Compara os lançamentos do ERP e do Banco e retorna `resultado` — um único
    DataFrame (Regra 2, 2026-07-10-b, ver docs/HISTORICO_DECISOES.md): o
    Resultado.xlsx passou a ter uma única aba, com todo o diagnóstico que
    antes vivia em abas separadas agora em colunas da própria linha.

    `config_ia` (opcional, `src/ia_config.ConfiguracaoIA`) liga a camada de IA
    decisiva (ver `src/ia_revisor.py` e docs/HISTORICO_DECISOES.md) — 2ª etapa
    que só analisa o que sobrar em Revisão Manual depois de TODAS as fases
    abaixo. Quando `None` (default — usado pelos 61+ testes que já existiam
    antes dessa funcionalidade) ou `config_ia.modo == IA_MODO_DESATIVADA`,
    nenhuma linha é enviada à IA e `COLUNAS_RESULTADO` fica exatamente como
    sempre foi — nenhuma coluna nova é criada. `cliente_ia` é injetável só
    para testes (um cliente falso e determinístico); em produção, `main.py`
    nunca precisa passá-lo.

    Segue a ordem obrigatória do CLAUDE.md: só o lado do banco de um lote NET
    EMP/EMPR claro é reservado ANTES de qualquer conciliação individual (passo
    6) — nunca entra nas fases 1 (exata) e 2 (tolerância). O lado do ERP
    (Salário/Folha, Férias, Rescisão, 13º) participa normalmente da
    conciliação individual contra todo o banco que não é lote — permitindo que
    um pagamento individual legítimo (ex.: funcionário pago fora do lote, via
    PIX nomeado) seja conciliado corretamente antes do lote. Só quando um
    lançamento ERP desse tipo fica ambíguo (sem par seguro) na conciliação
    individual, e existe um lote bancário claro do mesmo tipo por perto, ele é
    adiado (não finalizado como Revisão Manual) para a etapa de lote tentar —
    proteção reativa em vez de bloqueio prévio (decisão revisada em
    2026-07-10; ver docs/HISTORICO_DECISOES.md). A conciliação do lote em si
    continua sempre automática (total direto -> combinação única ->
    nome/descrição); não depende de nenhuma marcação manual do usuário.
    """
    df_erp = df_erp.reset_index(drop=True).copy()
    df_banco = df_banco.reset_index(drop=True).copy()

    # Regra revisada em 2026-07-10 (ver docs/HISTORICO_DECISOES.md): Vencimento
    # nunca é usado para conciliar. Uma linha do ERP sem nenhuma data de
    # pagamento/compensação/confirmação real (Data ERP Usada = NaT, porque
    # src/leitor_erp.py não preenche mais com o Vencimento) nunca tenta casar
    # com o banco — vai direto para Revisão Manual com motivo específico,
    # antes de qualquer fase de conciliação.
    indices_erp_sem_data = [i for i in df_erp.index if pd.isna(df_erp.at[i, "Data ERP Usada"])]
    linhas_sem_data_pagamento = [
        _linha_resultado_erp(
            df_erp.loc[i], STATUS_REVISAO_MANUAL, MOTIVO_SEM_DATA_PAGAMENTO, TIPO_REVISAO_MANUAL,
            pd.NaT, None, None, None, motivo_revisao=MOTIVO_SEM_DATA_PAGAMENTO,
        )
        for i in indices_erp_sem_data
    ]
    if indices_erp_sem_data:
        logger.info(
            f"Lançamentos do ERP sem data de pagamento/compensação (só vencimento, ou nenhuma data — "
            f"Revisão Manual, nunca tentam casar com o banco): {len(indices_erp_sem_data)}"
        )
    df_erp = df_erp.loc[~df_erp.index.isin(indices_erp_sem_data)].copy()

    df_erp["_valor_abs"] = df_erp["Valor"].abs().round(2)
    df_banco["_valor_abs"] = df_banco["Valor"].abs().round(2)
    df_erp["_chave_exata"] = list(zip(df_erp["_valor_abs"], df_erp["Data ERP Usada"]))
    df_banco["_chave_exata"] = list(zip(df_banco["_valor_abs"], df_banco["Data"]))

    logger.info(f"Desempate por descrição (USAR_DESCRICAO_PARA_DESEMPATE): {USAR_DESCRICAO_PARA_DESEMPATE}")

    # Passo 6 do CLAUDE.md: separa lote NET EMP/EMPR do lado do banco ANTES de
    # qualquer conciliação individual (passo 7). Só o banco é reservado aqui —
    # o ERP participa da conciliação individual normalmente (ver docstring).
    indices_banco_lote_reservados = [
        j for j in df_banco.index if _e_candidato_lote_banco(df_banco.at[j, "Favorecido"])
    ]
    indices_banco_individual = [j for j in df_banco.index if j not in set(indices_banco_lote_reservados)]
    df_banco_individual = df_banco.loc[indices_banco_individual]
    logger.info(
        f"Lançamentos do banco reservados para lote NET EMP/EMPR (fora da conciliação individual): "
        f"{len(indices_banco_lote_reservados)} de {len(df_banco)}"
    )

    # Mapa (tipo -> datas dos lotes bancários claros) usado só para decidir,
    # de forma reativa, se um lançamento ERP ambíguo na conciliação individual
    # deve ser adiado para a etapa de lote em vez de virar Revisão Manual por
    # coincidência (ver _resolver_grupo_ambiguo e _resolver_correspondencias_por_tolerancia).
    datas_por_tipo_lote_banco: dict = {}
    for j in indices_banco_lote_reservados:
        tipo_banco = _classificar_tipo_lote(df_banco.at[j, "Favorecido"]) or TIPO_LOTE_GENERICO
        datas_por_tipo_lote_banco.setdefault(tipo_banco, []).append(df_banco.at[j, "Data"])

    def _e_tipo_lote_erp(i) -> bool:
        """Só o tipo (Salário/Folha, Férias, Rescisão, 13º), sem checar data —
        usado para nunca deixar esses lançamentos usarem tolerância de data
        (Mudança 2026-07-10, regra 1)."""
        categoria = df_erp.at[i, "Categoria"] if "Categoria" in df_erp.columns else ""
        return _classificar_tipo_lote(df_erp.at[i, "Favorecido"], categoria) is not None

    def _e_candidato_lote_erp(i) -> bool:
        """Tipo + data EXATA (Mudança 2026-07-10: lote NET EMP não usa
        tolerância de data) igual à de algum lote bancário claro do mesmo tipo."""
        categoria = df_erp.at[i, "Categoria"] if "Categoria" in df_erp.columns else ""
        tipo = _classificar_tipo_lote(df_erp.at[i, "Favorecido"], categoria)
        if tipo is None:
            return False
        data_erp = df_erp.at[i, "Data ERP Usada"]
        if pd.isna(data_erp):
            return False
        return data_erp in datas_por_tipo_lote_banco.get(tipo, [])

    # Passos 7 a 10: conciliação individual (exata, tolerância, duplicidade
    # idêntica/equivalente e desempate por nome já embutidos em cada fase) —
    # roda sobre TODO o ERP (inclusive remuneração/férias/rescisão/13º) contra
    # o banco que não é lote NET EMP/EMPR claro. Um lançamento ERP de lote sem
    # par seguro é adiado (via `_e_candidato_lote_erp`) em vez de virar Revisão
    # Manual, e segue pendente para a etapa de lote. Na fase de tolerância,
    # lançamentos de lote nunca tentam par por proximidade de data
    # (`_e_tipo_lote_erp` — Mudança 2026-07-10).
    linhas_exatas, resolvidos_erp, resolvidos_banco = _resolver_correspondencias_exatas(
        df_erp, df_banco_individual, _e_candidato_lote_erp
    )
    linhas_tolerancia, indices_erp_pendentes, indices_banco_pendentes = _resolver_correspondencias_por_tolerancia(
        df_erp, df_banco_individual, resolvidos_erp, resolvidos_banco, _e_tipo_lote_erp
    )

    # Passo 11: lote NET EMP/EMPR por soma consolidada — usa só o que sobrou
    # da conciliação individual (nunca reutiliza um lançamento já conciliado).
    linhas_lote, resolvidos_erp_lote, resolvidos_banco_lote = _resolver_lote_net_empr(
        df_erp, df_banco, indices_erp_pendentes, indices_banco_lote_reservados, logger
    )

    indices_erp_finais = [i for i in indices_erp_pendentes if i not in resolvidos_erp_lote]
    indices_banco_finais = [j for j in indices_banco_pendentes if j not in resolvidos_banco_lote]

    # Verificação final (regra revisada em 2026-07-10, ver docs/HISTORICO_DECISOES.md):
    # antes de finalizar como "Não encontrado no banco", checa se existe um
    # possível par no banco (usado ou não) — só sobre o que sobrou de TODAS as
    # fases anteriores, para nunca interferir na conciliação individual, PIX/
    # TED/DOC, NET EMP, duplicidades ou combinação exata. Já finaliza 100% do
    # ERP pendente (Regra 2) — só o lado Banco pode sobrar para
    # `_finalizar_sem_correspondencia`.
    linhas_recuperadas, erp_recuperados, banco_recuperados = (
        _verificar_possiveis_pares_nao_encontrados(df_erp, df_banco, indices_erp_finais, indices_banco_finais, logger)
    )
    indices_erp_finais_restantes = [i for i in indices_erp_finais if i not in erp_recuperados]
    indices_banco_finais_restantes = [j for j in indices_banco_finais if j not in banco_recuperados]
    linhas_finais = _finalizar_sem_correspondencia(df_erp, df_banco, indices_erp_finais_restantes, indices_banco_finais_restantes)

    linhas_brutas = (
        linhas_sem_data_pagamento + linhas_exatas + linhas_tolerancia + linhas_lote
        + linhas_recuperadas + linhas_finais
    )

    # Camada de IA (2ª etapa decisiva — ver src/ia_revisor.py e
    # docs/HISTORICO_DECISOES.md): roda depois de TODAS as fases
    # determinísticas acima, mas ANTES de `_consolidar_pares_conciliados`,
    # para que uma decisão CONCILIAR aplicada em IA_MODO=AUTOMATICO produza
    # linhas no mesmo formato (`_par_id=(i, j)`) que qualquer fase
    # determinística já produz — a consolidação existente funde o par sem
    # precisar de nenhuma alteração. Import local só para evitar import
    # circular (src/ia_revisor.py importa várias constantes/funções deste
    # módulo). Quando config_ia é None/DESATIVADA, este bloco nunca roda e
    # COLUNAS_RESULTADO fica exatamente como sempre foi.
    ia_ativa = config_ia is not None and config_ia.modo != IA_MODO_DESATIVADA
    if ia_ativa:
        from src.ia_revisor import COLUNAS_IA, aplicar_decisoes_ia

        linhas_brutas = aplicar_decisoes_ia(
            linhas_brutas, df_erp, df_banco, indices_banco_lote_reservados, config_ia, logger,
            cliente_ia=cliente_ia,
        )

    # Regra 1 (2026-07-10-b): consolida cada par ERP x Banco efetivamente
    # conciliado numa única linha antes de montar o DataFrame final — nunca
    # exporta o mesmo par duas vezes (ver `_consolidar_pares_conciliados`).
    # Reaproveitada sem nenhuma alteração pelos pares decididos pela IA.
    todas_linhas = _consolidar_pares_conciliados(linhas_brutas, logger)

    colunas_finais = COLUNAS_RESULTADO + COLUNAS_IA if ia_ativa else COLUNAS_RESULTADO
    resultado = pd.DataFrame(todas_linhas, columns=colunas_finais)
    resultado = resultado.sort_values(by=["Data ERP Usada", "Data Banco"], na_position="last").reset_index(drop=True)

    _logar_resumo(resultado, logger)
    return resultado


def _logar_resumo(resultado: pd.DataFrame, logger: logging.Logger) -> None:
    contagem_status = resultado["Status"].value_counts().to_dict()
    for status in (STATUS_CONCILIADO, STATUS_REVISAO_MANUAL, STATUS_NAO_ENCONTRADO_BANCO, STATUS_SOMENTE_BANCO):
        logger.info(f"{status}: {contagem_status.get(status, 0)}")

    conciliados = resultado[resultado["Status"] == STATUS_CONCILIADO]
    contagem_tipo = conciliados["Tipo Conciliação"].value_counts().to_dict()
    logger.info(f"Conciliado por valor e data: {contagem_tipo.get(TIPO_VALOR_E_DATA, 0)}")
    logger.info(f"Conciliado por valor, data e descrição: {contagem_tipo.get(TIPO_VALOR_DATA_DESCRICAO, 0)}")
    logger.info(f"Conciliado por valor, data e nome: {contagem_tipo.get(TIPO_VALOR_DATA_NOME, 0)}")
    logger.info(f"Conciliado por duplicidade idêntica individual: {contagem_tipo.get(TIPO_DUPLICIDADE_IDENTICA, 0)}")
    logger.info(f"Conciliado por duplicidade equivalente individual: {contagem_tipo.get(TIPO_DUPLICIDADE_EQUIVALENTE, 0)}")
    logger.info(f"Conciliado por lote NET EMP (total direto): {contagem_tipo.get(TIPO_CONCILIACAO_LOTE_CONSOLIDADO, 0)}")
    logger.info(f"Conciliado por lote NET EMP (combinação exata única): {contagem_tipo.get(TIPO_LOTE_COMBINACAO_UNICA, 0)}")
    logger.info(f"Conciliado por lote NET EMP (nome/descrição): {contagem_tipo.get(TIPO_LOTE_POR_NOME, 0)}")
    logger.info(f"Conciliado pela camada de IA (IA_MODO=AUTOMATICO): {contagem_tipo.get(TIPO_CONCILIACAO_IA, 0)}")

    motivos_lote = resultado["Motivo Revisão"].astype(str).str.startswith((
        MOTIVO_LOTE_ERP_MENOR_QUE_BANCO, MOTIVO_LOTE_MULTIPLAS_COMBINACOES,
        MOTIVO_LOTE_NENHUMA_COMBINACAO, MOTIVO_LOTE_BANCO_GENERICO_SEM_COMBINACAO,
    ))
    logger.info(f"Lotes NET EMP em Revisão Manual (linhas): {int(motivos_lote.sum())}")
