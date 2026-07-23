"""Protege a camada de IA como 2ª etapa DECISIVA de conciliação (ver CLAUDE.md
e docs/HISTORICO_DECISOES.md): roda só depois de todas as regras
determinísticas, sobre o que sobrar em Revisão Manual elegível; nunca aplica
nada em IA_MODO=DESATIVADA (nem cria as colunas de IA) nem em IA_MODO=SOMBRA;
só aplica automaticamente em IA_MODO=AUTOMATICO quando passa em TODAS as
revalidações do Python, incluindo confiança mínima diferenciada por modo
(SOMBRA 0.70 / AUTOMATICO 0.95) e tolerância de data zero (revisada em
2026-07-23, ver CLAUDE.md "Regra de data exata"): candidatos de outra data
nunca são oferecidos à IA, e uma decisão que referencie um candidato fora da
lista oferecida é sempre rejeitada como formato inválido; nunca aplica quando
2+ lançamentos disputam o mesmo candidato bancário.

Usa sempre um `cliente_ia` falso e determinístico, injetado via
`conciliar(..., cliente_ia=...)` — nenhum teste aqui faz chamada de rede real.
"""

from datetime import date

from src.conciliador import COLUNAS_RESULTADO, STATUS_CONCILIADO, STATUS_REVISAO_MANUAL, TIPO_CONCILIACAO_IA, conciliar
from src.ia_config import ConfiguracaoIA
from src.ia_revisor import COLUNAS_IA
from tests.conftest import construir_df_banco, construir_df_erp


def _config(modo, **overrides):
    base = dict(
        modo=modo, api_key="sk-teste", modelo="openai/gpt-oss-120b",
        janela_busca_dias=0, janela_automatica_dias=0,
        maximo_candidatos=5, confianca_minima_sombra=0.70, confianca_minima_automatico=0.95,
    )
    base.update(overrides)
    return ConfiguracaoIA(**base)


def _cliente_por_favorecido(respostas: dict, default=("MANTER_REVISAO", None, 0.5, "sem regra de teste no fake")):
    """Cliente de IA falso: decide a resposta olhando qual trecho de
    `respostas` aparece no prompt do usuário (que sempre inclui o
    Favorecido do ERP — ver `_construir_prompt`). `respostas` mapeia
    trecho -> (decisao, candidato, confianca, motivo)."""
    chamadas = []

    def _cliente(sistema, usuario, labels, modelo, api_key):
        chamadas.append(usuario)
        for trecho, resposta in respostas.items():
            if trecho in usuario:
                decisao, candidato, confianca, motivo = resposta
                return {"decisao": decisao, "candidato": candidato, "confianca": confianca, "motivo": motivo}
        decisao, candidato, confianca, motivo = default
        return {"decisao": decisao, "candidato": candidato, "confianca": confianca, "motivo": motivo}

    _cliente.chamadas = chamadas
    return _cliente


# ---------------------------------------------------------------------------
# DESATIVADA (default) — zero diferença de comportamento e de colunas
# ---------------------------------------------------------------------------


def test_config_none_mantem_colunas_e_comportamento_atuais(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert list(resultado.columns) == COLUNAS_RESULTADO
    for coluna in COLUNAS_IA:
        assert coluna not in resultado.columns
    assert resultado.loc[resultado["Origem"] == "ERP", "Status"].eq(STATUS_REVISAO_MANUAL).all()


def test_config_desativada_explicita_tambem_nao_cria_colunas(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("DESATIVADA"))

    assert list(resultado.columns) == COLUNAS_RESULTADO


# ---------------------------------------------------------------------------
# SOMBRA — mesma análise/validação, nunca aplica
# ---------------------------------------------------------------------------


def test_sombra_aprovado_nunca_altera_status(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])
    cliente = _cliente_por_favorecido({"Fornecedor Solo Ltda": ("CONCILIAR", "C1", 0.80, "Nome e valor batem.")})

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("SOMBRA"), cliente_ia=cliente)

    assert list(resultado.columns) == COLUNAS_RESULTADO + COLUNAS_IA
    linha_erp = resultado[resultado["Origem"] == "ERP"].iloc[0]
    assert linha_erp["Status"] == STATUS_REVISAO_MANUAL
    assert linha_erp["Decisão IA"] == "CONCILIAR"
    assert linha_erp["Validação IA"] == "Aprovada (modo sombra, não aplicado)"
    assert linha_erp["Confiança IA"] == 0.80
    # Nunca mesclado em ERP+Banco: continua com a linha espelhada do banco.
    assert "ERP+Banco" not in resultado["Origem"].values


def test_sombra_rejeita_candidato_fora_da_lista_oferecida_e_nunca_aplica(logger_silencioso):
    # Gama e Delta disputam ZZZ (mesma data) -> só ZZZ é oferecido à IA como
    # candidato; "GAMA TARDIO" (3 dias depois) tem data diferente e nunca
    # entra na lista (tolerância de data zero). O cliente fake ainda assim
    # "escolhe" C2, um candidato que não foi oferecido: a validação de
    # formato do Python rejeita isso, independentemente do modo.
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 900.00, "favorecido": "Fornecedor Gama"},
        {"data_usada": date(2026, 6, 10), "valor": 900.00, "favorecido": "Fornecedor Delta"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -900.00, "favorecido": "PAGAMENTO GENERICO ZZZ"},
        {"data": date(2026, 6, 13), "valor": -900.00, "favorecido": "PAGAMENTO GAMA TARDIO"},
    ])
    cliente = _cliente_por_favorecido({
        "Fornecedor Gama": ("CONCILIAR", "C2", 0.97, "Candidato mais distante corresponde ao nome."),
        "Fornecedor Delta": ("MANTER_REVISAO", None, 0.10, "Nenhum candidato claro."),
    })

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("SOMBRA"), cliente_ia=cliente)

    linha_gama = resultado[resultado["Descrição ERP"] == "Fornecedor Gama"].iloc[0]
    assert linha_gama["Status"] == STATUS_REVISAO_MANUAL
    assert linha_gama["Decisão IA"] == "Erro na consulta à IA"
    assert linha_gama["Validação IA"] == "Rejeitada: resposta da IA em formato inválido"


# ---------------------------------------------------------------------------
# AUTOMATICO — confiança mínima diferenciada e tolerância de data zero
# ---------------------------------------------------------------------------


def test_automatico_confianca_abaixo_do_minimo_automatico_nao_aplica(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])
    # 0.80 passaria em SOMBRA (>= 0.70) mas não em AUTOMATICO (< 0.95).
    cliente = _cliente_por_favorecido({"Fornecedor Solo Ltda": ("CONCILIAR", "C1", 0.80, "Razoavelmente parecido.")})

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    linha_erp = resultado[resultado["Origem"] == "ERP"].iloc[0]
    assert linha_erp["Status"] == STATUS_REVISAO_MANUAL
    assert linha_erp["Validação IA"].startswith("Rejeitada: confiança abaixo do mínimo")


def test_automatico_aplica_quando_confianca_alta_e_dentro_da_janela_automatica(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])
    cliente = _cliente_por_favorecido({"Fornecedor Solo Ltda": ("CONCILIAR", "C1", 0.97, "Único candidato, valor exato.")})

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    linha = resultado[resultado["Origem"] == "ERP+Banco"].iloc[0]
    assert linha["Status"] == STATUS_CONCILIADO
    assert linha["Tipo Conciliação"] == TIPO_CONCILIACAO_IA
    assert linha["Origem"] == "ERP+Banco"
    assert linha["Data Banco"] == date(2026, 6, 10)
    assert linha["Valor Banco"] == -700.00
    assert linha["Descrição Banco"] == "PAGAMENTO GENERICO XPTO"
    assert linha["Validação IA"] == "Aprovada e conciliado automaticamente"
    assert linha["Modelo IA"] == "openai/gpt-oss-120b"


def test_automatico_rejeita_candidato_fora_da_lista_oferecida_e_nao_aplica(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 900.00, "favorecido": "Fornecedor Gama"},
        {"data_usada": date(2026, 6, 10), "valor": 900.00, "favorecido": "Fornecedor Delta"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -900.00, "favorecido": "PAGAMENTO GENERICO ZZZ"},
        {"data": date(2026, 6, 13), "valor": -900.00, "favorecido": "PAGAMENTO GAMA TARDIO"},  # data diferente: nunca oferecido à IA
    ])
    cliente = _cliente_por_favorecido({
        "Fornecedor Gama": ("CONCILIAR", "C2", 0.97, "Candidato mais distante corresponde ao nome."),
        "Fornecedor Delta": ("MANTER_REVISAO", None, 0.10, "Nenhum candidato claro."),
    })

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    linha_gama = resultado[resultado["Descrição ERP"] == "Fornecedor Gama"].iloc[0]
    assert linha_gama["Status"] == STATUS_REVISAO_MANUAL
    assert linha_gama["Validação IA"] == "Rejeitada: resposta da IA em formato inválido"
    assert "ERP+Banco" not in resultado["Origem"].values


def test_automatico_conflito_entre_dois_erp_nenhum_e_aplicado(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Alfa Ltda"},
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Beta Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])
    # As duas propostas "escolhem" o mesmo (único) candidato disponível.
    cliente = _cliente_por_favorecido({}, default=("CONCILIAR", "C1", 0.99, "Bate com o único candidato."))

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    linhas_erp = resultado[resultado["Origem"] == "ERP"]
    assert len(linhas_erp) == 2
    assert (linhas_erp["Status"] == STATUS_REVISAO_MANUAL).all()
    assert linhas_erp["Validação IA"].str.startswith("Rejeitada: conflito com outro lançamento").all()
    assert "ERP+Banco" not in resultado["Origem"].values


def test_automatico_sem_candidato_disponivel_nunca_chama_ia(logger_silencioso):
    # A verificação determinística de "Não encontrado no banco" acha esse par
    # por nome forte em outra data (sem limite de dias) e deixa a linha em
    # Revisão Manual — mas a busca de candidatos da própria IA exige a mesma
    # data (IA_JANELA_BUSCA_DIAS=0) e não alcança um banco a 19 dias de
    # distância, então a IA nunca chega a ser chamada para este lançamento.
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 1), "valor": 555.00, "favorecido": "Fornecedor Tardio Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 20), "valor": -555.00, "favorecido": "PAGAMENTO FORNECEDOR TARDIO LTDA"},
    ])
    cliente = _cliente_por_favorecido({})

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    assert cliente.chamadas == []
    linha_erp = resultado[resultado["Origem"] == "ERP"].iloc[0]
    assert linha_erp["Status"] == STATUS_REVISAO_MANUAL
    assert linha_erp["Decisão IA"] == "Sem candidato disponível"
    assert linha_erp["Validação IA"] == "Não aplicável"
    assert linha_erp["Modelo IA"] is None or (isinstance(linha_erp["Modelo IA"], float))


def test_erro_na_consulta_a_ia_mantem_revisao_manual_sem_quebrar(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
        {"data": date(2026, 6, 10), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO ABC"},
    ])

    def _cliente_com_falha(sistema, usuario, labels, modelo, api_key):
        raise RuntimeError("timeout simulado")

    resultado = conciliar(
        df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=_cliente_com_falha,
    )

    linha_erp = resultado[resultado["Origem"] == "ERP"].iloc[0]
    assert linha_erp["Status"] == STATUS_REVISAO_MANUAL
    assert linha_erp["Decisão IA"] == "Erro na consulta à IA"
    assert linha_erp["Validação IA"] == "Rejeitada: falha na comunicação com a IA"


# ---------------------------------------------------------------------------
# Motivos removidos da lista branca (2026-07-10, revisão 3 do plano) nunca
# chegam a chamar a IA, em nenhum modo — teste de integração complementar ao
# unitário de tests/test_ia_revisor_candidatos.py.
# ---------------------------------------------------------------------------


def test_motivo_quantidade_divergente_nunca_chama_ia(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 10.00, "favorecido": "Tarifa Banco"},
        {"data_usada": date(2026, 6, 10), "valor": 10.00, "favorecido": "Tarifa Banco"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 10), "valor": -10.00, "favorecido": "Tarifa Banco"},
        {"data": date(2026, 6, 10), "valor": -10.00, "favorecido": "Tarifa Banco"},
        {"data": date(2026, 6, 10), "valor": -10.00, "favorecido": "Tarifa Banco"},
    ])
    cliente = _cliente_por_favorecido({}, default=("CONCILIAR", "C1", 0.99, "não deveria ser chamado"))

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    assert cliente.chamadas == []
    assert (resultado["Status"] == STATUS_REVISAO_MANUAL).all()


# ---------------------------------------------------------------------------
# Integridade estrutural
# ---------------------------------------------------------------------------


def test_indices_internos_nunca_vazam_mesmo_com_ia_ativa(logger_silencioso):
    df_erp = construir_df_erp([
        {"data_usada": date(2026, 6, 10), "valor": 700.00, "favorecido": "Fornecedor Solo Ltda"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 6, 11), "valor": -700.00, "favorecido": "PAGAMENTO GENERICO XPTO"},
    ])
    cliente = _cliente_por_favorecido({"Fornecedor Solo Ltda": ("CONCILIAR", "C1", 0.97, "ok")})

    resultado = conciliar(df_erp, df_banco, logger_silencioso, config_ia=_config("AUTOMATICO"), cliente_ia=cliente)

    for coluna_interna in ("_erp_index", "_banco_index", "_par_id"):
        assert coluna_interna not in resultado.columns
