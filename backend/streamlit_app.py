"""Interface Streamlit local do Conciliador Bancário.

A aplicação reutiliza integralmente o pipeline oficial em ``src.web_runner``.
Nenhuma regra de conciliação é implementada nesta camada de apresentação.
"""

from __future__ import annotations

import base64
import contextlib
import html
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

from src.logger import obter_logger
from src.web_runner import executar_conciliacao_web


RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_RUNTIME = Path(
    os.environ.get(
        "CONCILIADOR_RUNTIME_DIR",
        RAIZ_PROJETO / ".web-runtime" / "streamlit",
    )
)
CSS_PATH = RAIZ_PROJETO / "streamlit_ui" / "styles.css"
LIMITE_ARQUIVO_BYTES = 30 * 1024 * 1024
PAGE_SIZE_PENDENCIAS = 8

# Logger que `executar_conciliacao_web` usa (ver src/web_runner.py). A captura
# abaixo só o observa — nunca altera a configuração de log do projeto, então o
# arquivo diário em backend/logs/ continua sendo gravado normalmente.
NOME_LOGGER_PIPELINE = "conciliador_web"
LIMITE_LINHAS_LOG = 2000

EXTENSOES_ERP = {".xlsx", ".xls"}
EXTENSOES_BANCO = {".ofx", ".xlsx", ".xls"}

# st.html() sanitiza a saída com DOMPurify em USE_PROFILES:{html:true}, que
# remove qualquer <svg> inline (mesmo sem <script>). Por isso os ícones são
# gerados como <img src="data:image/svg+xml;base64,...">, com a cor do traço
# já fixada no próprio SVG — currentColor não atravessa para uma imagem à parte.
_ICONE_VIEWBOX = {
    "building": "0 0 28 28",
    "bank": "0 0 28 28",
    "brand": "0 0 32 32",
    "check": "0 0 28 28",
    "review": "0 0 28 28",
}

_ICONE_PATHS = {
    "building": (
        '<path d="M6 24V7l8-4 8 4v17M3.5 24.5h21"/>'
        '<path d="M10 9h2v2h-2zM16 9h2v2h-2zM10 14h2v2h-2zM16 14h2v2h-2z'
        'M10 19h2v2h-2zM16 19h2v2h-2z"/>'
    ),
    "bank": (
        '<path d="m3 10 11-7 11 7H3Z"/>'
        '<path d="M6 12v9M11.3 12v9M16.7 12v9M22 12v9M3 24h22M5 21h18"/>'
    ),
    "brand": (
        '<path d="M5 8.5A3.5 3.5 0 0 1 8.5 5h15A3.5 3.5 0 0 1 27 8.5v15a3.5 '
        '3.5 0 0 1-3.5 3.5h-15A3.5 3.5 0 0 1 5 23.5v-15Z"/>'
        '<path d="M10 11h12M10 16h7M10 21h12"/>'
        '<path d="m20 14 2.5 2.5L20 19"/>'
    ),
    "check": (
        '<circle cx="14" cy="14" r="11"/>'
        '<path d="m8.5 14 3.5 3.5 7.5-8"/>'
    ),
    "review": (
        '<path d="M14 3.5 25 23H3L14 3.5Z"/>'
        '<path d="M14 10v6M14 20h.01"/>'
    ),
}


def _icone(nome: str, cor: str, largura: float = 1.7) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_ICONE_VIEWBOX[nome]}" fill="none" stroke="{cor}" '
        f'stroke-width="{largura}" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICONE_PATHS[nome]}</svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="icone-svg" alt="" src="data:image/svg+xml;base64,{b64}"/>'


COR_NAVY_900 = "#08264b"
COR_BRANCO = "#ffffff"
COR_BANK_HERO = "#086b9d"
COR_SUCCESS = "#287a52"
COR_REVIEW = "#9a6500"
COR_METRIC_ERP = "#0a5e99"
COR_METRIC_BANK = "#08658f"
COR_METRIC_SUCCESS = "#2d704c"
COR_METRIC_REVIEW = "#855500"
COR_METRIC_DANGER = "#a3292e"


class _CapturaDeLog(logging.Handler):
    """Guarda em memória as linhas de log de uma única execução.

    O ``deque`` com ``maxlen`` limita o consumo de memória: numa execução muito
    longa, as linhas mais antigas são descartadas em vez de crescer sem fim.
    """

    def __init__(self, limite: int = LIMITE_LINHAS_LOG) -> None:
        super().__init__()
        self.linhas: deque[str] = deque(maxlen=limite)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    def emit(self, registro: logging.LogRecord) -> None:
        try:
            self.linhas.append(self.format(registro))
        except Exception:  # noqa: BLE001 — log nunca pode derrubar a execução.
            pass


@contextlib.contextmanager
def _capturar_log_da_execucao():
    """Observa o logger do pipeline apenas enquanto a conciliação roda.

    O handler é anexado na entrada e removido no ``finally``, mesmo se a
    conciliação falhar. Antes de anexar, qualquer captura remanescente de uma
    execução anterior é retirada — assim reruns do Streamlit nunca acumulam
    handlers duplicados nem misturam o log de duas execuções.

    Deixa o próprio ``src.logger`` configurar o logger antes de observá-lo:
    ``obter_logger`` retorna adiantado quando o logger já tem handlers, então
    anexar a captura primeiro impediria o ``setLevel(INFO)`` e as mensagens
    seriam descartadas pelo nível herdado da raiz. Assim o arquivo diário em
    ``backend/logs/`` também continua sendo gravado normalmente.
    """
    logger = obter_logger(NOME_LOGGER_PIPELINE)

    for handler in [h for h in logger.handlers if isinstance(h, _CapturaDeLog)]:
        logger.removeHandler(handler)

    captura = _CapturaDeLog()
    logger.addHandler(captura)
    try:
        yield captura
    finally:
        logger.removeHandler(captura)


def _inicializar_estado() -> None:
    valores_iniciais = {
        "resultado_conciliacao": None,
        "resultado_excel": None,
        "assinatura_processada": None,
        "nome_resultado": "Resultado.xlsx",
        "log_execucao": [],
    }
    for chave, valor in valores_iniciais.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def _formatar_moeda(valor: Any) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    texto = f"{numero:,.2f}"
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _formatar_percentual(valor: Any) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        numero = 0.0
    return f"{numero:.1f}%".replace(".", ",")


def _formatar_data(valor: Any) -> str:
    if not valor:
        return "—"
    texto = str(valor)[:10]
    partes = texto.split("-")
    if len(partes) == 3:
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto


def _nome_seguro(nome: str, padrao: str) -> str:
    nome_base = Path(nome.replace("\\", "/")).name
    sufixo = Path(nome_base).suffix.lower()
    radical = Path(nome_base).stem
    radical = re.sub(r"[^A-Za-z0-9._-]+", "_", radical).strip("._")
    return f"{radical or padrao}{sufixo}"


def _assinatura_arquivos(arquivo_erp, arquivo_banco) -> tuple | None:
    if arquivo_erp is None or arquivo_banco is None:
        return None
    return (
        arquivo_erp.name,
        arquivo_erp.size,
        arquivo_banco.name,
        arquivo_banco.size,
    )


def _validar_upload(arquivo, tipo: str) -> str | None:
    if arquivo is None:
        return None

    extensao = Path(arquivo.name).suffix.lower()
    permitidas = EXTENSOES_ERP if tipo == "erp" else EXTENSOES_BANCO
    if extensao not in permitidas:
        formatos = "XLSX ou XLS" if tipo == "erp" else "OFX, XLSX ou XLS"
        return f"O arquivo de {tipo.upper()} deve estar em formato {formatos}."
    if arquivo.size > LIMITE_ARQUIVO_BYTES:
        return "Cada arquivo deve ter no máximo 30 MB."
    return None


def _cabecalho_html() -> str:
    return f"""
    <header class="app-shell-header">
      <div class="app-brand">
        <span class="brand-mark">{_icone('brand', COR_BRANCO)}</span>
        <span class="brand-copy">
          <strong>concilia</strong>
          <small>ERP · Banco</small>
        </span>
      </div>
      <nav class="app-nav">
        <a href="#fluxo">Nova conciliação</a>
        <a href="#resultado">Resultado</a>
      </nav>
      <span class="local-badge"><i></i>Ambiente local</span>
    </header>
    """


def _hero_html() -> str:
    return f"""
    <section class="br-hero" aria-labelledby="titulo-principal">
      <h1 id="titulo-principal">
        <span>Bank</span>
        <strong>Conciliation</strong>
      </h1>
      <div class="reconciliation-signal" role="img"
           aria-label="Fluxo visual entre o ERP, a conciliação local e o banco">
        <div class="signal-source">
          <span>{_icone('building', COR_NAVY_900)}</span>
          <strong>ERP</strong>
        </div>
        <div class="signal-line"><i></i><i></i></div>
        <div class="signal-core">
          <span class="signal-ring"></span>
          <span class="signal-mark">{_icone('brand', COR_BRANCO)}</span>
        </div>
        <div class="signal-line"><i></i><i></i></div>
        <div class="signal-source signal-source-bank">
          <span>{_icone('bank', COR_BANK_HERO)}</span>
          <strong>Banco</strong>
        </div>
      </div>
    </section>
    """


def _etapas_html(tem_arquivos: bool, tem_resultado: bool) -> str:
    classe_arquivos = "complete" if tem_arquivos else "active"
    classe_resultado = "complete" if tem_resultado else ""
    return f"""
    <div class="section-heading">
      <div>
        <p>Nova execução</p>
        <h2>Selecione os arquivos do período</h2>
      </div>
      <ol class="step-list" aria-label="Etapas da conciliação">
        <li class="{classe_arquivos}"><span>1</span> Arquivos</li>
        <li><span>2</span> Processamento</li>
        <li class="{classe_resultado}"><span>3</span> Resultado</li>
      </ol>
    </div>
    """


def _upload_heading_html(tipo: str) -> str:
    if tipo == "erp":
        icone = _icone("building", COR_NAVY_900)
        titulo = "Relatório do ERP"
        descricao = "Contas a pagar exportadas do sistema ERP"
    else:
        icone = _icone("bank", COR_NAVY_900)
        titulo = "Extrato do banco"
        descricao = "Débitos bancários do mesmo período"
    return f"""
    <div class="upload-heading">
      <span>{icone}</span>
      <div><strong>{titulo}</strong><small>{descricao}</small></div>
    </div>
    """


def _metric_card(
    tom: str,
    rotulo: str,
    valor: str,
    detalhe: str,
    icone: str,
) -> str:
    return f"""
    <article class="metric-card metric-{tom}">
      <span class="metric-icon">{icone}</span>
      <div>
        <p>{html.escape(rotulo)}</p>
        <strong>{html.escape(valor)}</strong>
        <small>{html.escape(detalhe)}</small>
      </div>
    </article>
    """


def _metricas_html(resultado: dict | None) -> str:
    if resultado:
        indicadores = resultado["indicadores"]
        entradas = resultado["entradas"]
        conciliado = indicadores["conciliado"]
        revisao = indicadores["revisaoManual"]
        somente_banco = indicadores["somenteBanco"]
        valor_gestao = _formatar_moeda(indicadores["totalGestao"])
        detalhe_gestao = f'{entradas["linhasGestao"]} lançamentos lidos'
        valor_banco = _formatar_moeda(indicadores["totalBanco"])
        detalhe_banco = f'{entradas["linhasBanco"]} débitos considerados'
        valor_conciliado = (
            f'{conciliado["quantidade"]} · '
            f'{_formatar_percentual(conciliado["percentual"])}'
        )
        valor_revisao = (
            f'{revisao["quantidade"]} · '
            f'{_formatar_percentual(revisao["percentual"])}'
        )
        valor_somente_banco = (
            f'{somente_banco["quantidade"]} · '
            f'{_formatar_percentual(somente_banco["percentual"])}'
        )
        classe_extra = ""
    else:
        valor_gestao = valor_banco = "—"
        valor_conciliado = valor_revisao = valor_somente_banco = "—"
        detalhe_gestao = "Aguardando o relatório"
        detalhe_banco = "Aguardando o extrato"
        classe_extra = " is-empty"

    cards = [
        _metric_card(
            "erp",
            "Total na Gestão",
            valor_gestao,
            detalhe_gestao,
            _icone("building", COR_METRIC_ERP),
        ),
        _metric_card(
            "bank",
            "Total no banco",
            valor_banco,
            detalhe_banco,
            _icone("bank", COR_METRIC_BANK),
        ),
        _metric_card(
            "success",
            "Conciliado",
            valor_conciliado,
            "Correspondências confirmadas",
            _icone("check", COR_METRIC_SUCCESS),
        ),
        _metric_card(
            "review",
            "Revisão manual",
            valor_revisao,
            "Exige avaliação humana",
            _icone("review", COR_METRIC_REVIEW),
        ),
        _metric_card(
            "danger",
            "Somente no banco",
            valor_somente_banco,
            "Sem lançamento correspondente",
            _icone("bank", COR_METRIC_DANGER),
        ),
    ]
    return f'<div class="metric-grid{classe_extra}">{"".join(cards)}</div>'


def _filtrar_pendencias(
    pendencias: list[dict],
    busca: str,
    status: str,
) -> list[dict]:
    busca_normalizada = busca.casefold().strip()
    filtradas = []
    for item in pendencias:
        if status != "Todos" and item.get("status") != status:
            continue
        if busca_normalizada:
            texto_item = " ".join(
                str(item.get(chave) or "")
                for chave in ("data", "origem", "favorecido", "status", "motivo")
            ).casefold()
            if busca_normalizada not in texto_item:
                continue
        filtradas.append(item)
    return filtradas


def _status_pill_classe(status: str) -> str:
    if status == "Revisão Manual":
        return "status-pill--review"
    if status == "Somente banco":
        return "status-pill--danger"
    return ""


def _linha_tabela_html(item: dict) -> str:
    status = item.get("status") or "—"
    return f"""
    <tr>
      <td class="date-cell">{html.escape(_formatar_data(item.get('data')))}</td>
      <td>{html.escape(item.get('origem') or '—')}</td>
      <td class="description-cell">{html.escape(item.get('favorecido') or 'Sem descrição')}</td>
      <td class="numeric">{html.escape(_formatar_moeda(item.get('valorGestao')))}</td>
      <td class="numeric">{html.escape(_formatar_moeda(item.get('valorBanco')))}</td>
      <td><span class="status-pill {_status_pill_classe(status)}">{html.escape(status)}</span></td>
      <td class="reason-cell">{html.escape(item.get('motivo') or '—')}</td>
    </tr>
    """


def _tabela_pendencias_html(pagina_itens: list[dict]) -> str:
    if pagina_itens:
        corpo = "".join(_linha_tabela_html(item) for item in pagina_itens)
    else:
        corpo = """
        <tr>
          <td colspan="7">
            <div class="no-results">
              <strong>Nenhum item neste filtro</strong>
              <span>Limpe a busca ou selecione outro status.</span>
            </div>
          </td>
        </tr>
        """
    return f"""
    <div class="table-scroll">
      <table class="pendencias-table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Origem</th>
            <th>Favorecido ou descrição</th>
            <th class="numeric">Valor na Gestão</th>
            <th class="numeric">Valor no banco</th>
            <th>Status</th>
            <th>Motivo</th>
          </tr>
        </thead>
        <tbody>{corpo}</tbody>
      </table>
    </div>
    """


def _periodo_resultado(resultado: dict) -> str:
    periodo = resultado.get("periodo", {})
    inicio = periodo.get("inicio")
    fim = periodo.get("fim")
    if inicio and fim:
        return f"{_formatar_data(inicio)} a {_formatar_data(fim)}"
    return "Período identificado nos arquivos"


def _salvar_upload(arquivo, pasta: Path, padrao: str) -> None:
    nome = _nome_seguro(arquivo.name, padrao)
    (pasta / nome).write_bytes(bytes(arquivo.getbuffer()))


def _executar(arquivo_erp, arquivo_banco) -> None:
    identificador = str(uuid4())
    pasta_execucao = PASTA_RUNTIME / identificador
    pasta_erp = pasta_execucao / "erp"
    pasta_banco = pasta_execucao / "banco"
    pasta_erp.mkdir(parents=True, exist_ok=False)
    pasta_banco.mkdir(parents=True, exist_ok=False)
    caminho_resultado = pasta_execucao / "Resultado.xlsx"

    _salvar_upload(arquivo_erp, pasta_erp, "erp")
    _salvar_upload(arquivo_banco, pasta_banco, "banco")

    # Zera o log antes de começar: o expander só mostra a execução atual.
    st.session_state.log_execucao = []

    with _capturar_log_da_execucao() as captura:
        try:
            resposta = executar_conciliacao_web(
                pasta_erp,
                pasta_banco,
                caminho_resultado,
            )
        finally:
            # Preserva o log inclusive quando a conciliação falha — é
            # justamente aí que ele mais serve para diagnóstico.
            st.session_state.log_execucao = list(captura.linhas)

    st.session_state.resultado_conciliacao = resposta
    st.session_state.resultado_excel = caminho_resultado.read_bytes()
    st.session_state.assinatura_processada = _assinatura_arquivos(
        arquivo_erp,
        arquivo_banco,
    )
    st.session_state.nome_resultado = resposta.get(
        "arquivoResultado",
        "Resultado.xlsx",
    )
    st.session_state.execucao_id = identificador


def _resetar_paginacao_se_necessario(busca: str, status: str) -> None:
    assinatura = (busca, status, st.session_state.get("execucao_id"))
    if st.session_state.get("assinatura_filtro_pendencias") != assinatura:
        st.session_state.assinatura_filtro_pendencias = assinatura
        st.session_state.pagina_pendencias = 1


def _analysis_heading_html(resultado: dict | None) -> str:
    pendencias = resultado.get("pendentes", []) if resultado else []
    total = int(resultado.get("pendentesTotal", len(pendencias))) if resultado else 0
    if resultado:
        descricao = f'{total} registro{"" if total == 1 else "s"} precisa{"" if total == 1 else "m"} de atenção'
    else:
        descricao = "A tabela será preenchida após a conciliação"

    resumo = ""
    if resultado:
        nao_encontrado = resultado["indicadores"]["naoEncontradoBanco"]["quantidade"]
        exibidos = int(resultado.get("pendentesExibidos", len(pendencias)))
        resumo = f"""
        <div class="analysis-summary">
          <span><small>Não encontrados</small><strong>{nao_encontrado}</strong></span>
          <span><small>Prévia carregada</small><strong>{exibidos}/{total}</strong></span>
        </div>
        """
    return f"""
    <div class="analysis-heading">
      <div>
        <span class="analysis-heading__icon">{_icone('review', COR_REVIEW)}</span>
        <span>
          <h3>Itens pendentes de análise</h3>
          <p>{html.escape(descricao)}</p>
        </span>
      </div>
      {resumo}
    </div>
    """


def _renderizar_log_execucao() -> None:
    """Mostra o log da execução atual, para auditoria e diagnóstico.

    Fechado por padrão: é informação de apoio, não o resultado. O mesmo
    conteúdo continua sendo gravado no arquivo diário de ``backend/logs/``.
    """
    linhas = st.session_state.get("log_execucao") or []
    if not linhas:
        return

    with st.expander(f"Log da execução ({len(linhas)} linhas)", expanded=False):
        st.code("\n".join(linhas), language=None)


def _renderizar_resultado(resultado: dict | None) -> None:
    cabecalho, download = st.columns([3, 1], vertical_alignment="center")
    with cabecalho:
        periodo_label = (
            _periodo_resultado(resultado) if resultado else "Aguardando uma execução"
        )
        st.html(
            f"""
            <div class="results-heading">
              <p>Quadro detalhado de conciliação</p>
              <h2>Resultado da execução</h2>
              <span>{html.escape(periodo_label)}</span>
            </div>
            """
        )
    with download:
        st.download_button(
            "Baixar planilha final",
            data=st.session_state.resultado_excel or b"",
            file_name=st.session_state.nome_resultado,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            icon=":material/download:",
            type="primary",
            width="stretch",
            disabled=resultado is None,
            on_click="ignore",
            key="download_resultado",
        )

    st.html(_metricas_html(resultado))

    with st.container(key="analysis_panel"):
        st.html(_analysis_heading_html(resultado))

        if resultado:
            pendencias = resultado.get("pendentes", [])

            with st.container(key="table_toolbar"):
                busca_col, status_col = st.columns([2, 1])
                with busca_col:
                    busca = st.text_input(
                        "Pesquisar pendências",
                        placeholder="Pesquisar favorecido, motivo ou origem",
                        icon=":material/search:",
                        key="busca_pendencias",
                    )
                with status_col:
                    status = st.pills(
                        "Status",
                        (
                            "Todos",
                            "Revisão Manual",
                            "Não encontrado no banco",
                            "Somente banco",
                        ),
                        default="Todos",
                        label_visibility="collapsed",
                        key="filtro_status",
                    )

            _resetar_paginacao_se_necessario(busca, status)

            filtradas = _filtrar_pendencias(pendencias, busca, status)
            total_paginas = max(1, -(-len(filtradas) // PAGE_SIZE_PENDENCIAS))
            pagina_atual = min(
                max(1, st.session_state.get("pagina_pendencias", 1)),
                total_paginas,
            )
            st.session_state.pagina_pendencias = pagina_atual

            inicio = (pagina_atual - 1) * PAGE_SIZE_PENDENCIAS
            fim = inicio + PAGE_SIZE_PENDENCIAS
            st.html(_tabela_pendencias_html(filtradas[inicio:fim]))

            with st.container(key="table_footer"):
                rodape_texto, rodape_paginacao = st.columns(
                    [2, 1], vertical_alignment="center"
                )
                with rodape_texto:
                    mostrando_inicio = inicio + 1 if filtradas else 0
                    mostrando_fim = min(fim, len(filtradas))
                    st.caption(
                        f"Mostrando {mostrando_inicio}–{mostrando_fim} "
                        f"de {len(filtradas)}"
                    )
                with rodape_paginacao:
                    anterior_col, label_col, proxima_col = st.columns(
                        [1, 1, 1], vertical_alignment="center"
                    )
                    with anterior_col:
                        if st.button(
                            "Anterior",
                            key="pagina_anterior",
                            disabled=pagina_atual == 1,
                            width="stretch",
                        ):
                            st.session_state.pagina_pendencias = pagina_atual - 1
                            st.rerun()
                    with label_col:
                        st.markdown(
                            f"<div style='text-align:center'>{pagina_atual} / "
                            f"{total_paginas}</div>",
                            unsafe_allow_html=True,
                        )
                    with proxima_col:
                        if st.button(
                            "Próxima",
                            key="pagina_proxima",
                            disabled=pagina_atual == total_paginas,
                            width="stretch",
                        ):
                            st.session_state.pagina_pendencias = pagina_atual + 1
                            st.rerun()
        else:
            st.html(
                f"""
                <div class="empty-result">
                  <span>{_icone('brand', COR_BRANCO)}</span>
                  <div>
                    <h3>Pronto para a primeira conciliação</h3>
                    <p>Adicione os dois arquivos acima. As exceções aparecerão
                    aqui com data, valores, status e motivo.</p>
                    <a class="analysis-cta" href="#fluxo">Selecionar arquivos →</a>
                  </div>
                </div>
                """
            )

    _renderizar_log_execucao()


st.set_page_config(
    page_title="Concilia — Conciliador Bancário",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="collapsed",
)
_inicializar_estado()
st.html(CSS_PATH)
st.html(_cabecalho_html())
st.html(_hero_html())
st.html('<div id="fluxo"></div>')

with st.container(key="workflow_section"):
    arquivo_erp_atual = st.session_state.get("erp_upload")
    arquivo_banco_atual = st.session_state.get("banco_upload")
    tem_arquivos = arquivo_erp_atual is not None and arquivo_banco_atual is not None
    st.html(
        _etapas_html(
            tem_arquivos,
            st.session_state.resultado_conciliacao is not None,
        )
    )

    coluna_erp, coluna_banco = st.columns(2)
    with coluna_erp:
        with st.container(key="erp_upload_panel"):
            st.html(_upload_heading_html("erp"))
            arquivo_erp = st.file_uploader(
                "Relatório do ERP",
                type=["xlsx", "xls"],
                max_upload_size=30,
                label_visibility="collapsed",
                key="erp_upload",
            )
    with coluna_banco:
        with st.container(key="banco_upload_panel"):
            st.html(_upload_heading_html("banco"))
            arquivo_banco = st.file_uploader(
                "Extrato do banco",
                type=["ofx", "xlsx", "xls"],
                max_upload_size=30,
                label_visibility="collapsed",
                key="banco_upload",
            )

    erros = [
        erro
        for erro in (
            _validar_upload(arquivo_erp, "erp"),
            _validar_upload(arquivo_banco, "banco"),
        )
        if erro
    ]
    for erro in erros:
        st.error(erro, icon=":material/error:")

    assinatura_atual = _assinatura_arquivos(arquivo_erp, arquivo_banco)
    if (
        st.session_state.assinatura_processada is not None
        and assinatura_atual != st.session_state.assinatura_processada
    ):
        st.session_state.resultado_conciliacao = None
        st.session_state.resultado_excel = None
        st.session_state.assinatura_processada = None

    regra, acao = st.columns([2, 1], vertical_alignment="center")
    with regra:
        st.html(
            f"""
            <div class="execution-rule">
              <span>{_icone('check', COR_SUCCESS)}</span>
              <div>
                <strong>Regra central</strong>
                <small>Somente lançamentos com o mesmo valor absoluto e a mesma
                data podem conciliar.</small>
              </div>
            </div>
            """
        )
    with acao:
        executar = st.button(
            "Executar conciliação",
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
            disabled=(
                arquivo_erp is None
                or arquivo_banco is None
                or bool(erros)
            ),
            key="executar_conciliacao",
        )

    if executar:
        try:
            with st.status(
                "Executando a conciliação",
                expanded=True,
                type="compact",
            ) as status_execucao:
                st.write("Lendo os arquivos e validando o período.")
                st.write("Aplicando as regras de data, valor e descrição.")
                _executar(arquivo_erp, arquivo_banco)
                status_execucao.update(
                    label="Conciliação concluída",
                    state="complete",
                    expanded=False,
                )
        except Exception as erro:
            st.session_state.resultado_conciliacao = None
            st.session_state.resultado_excel = None
            st.error(
                "Não foi possível concluir a conciliação. "
                f"Verifique os arquivos enviados. Detalhe: {erro}",
                icon=":material/error:",
            )

st.html('<div id="resultado"></div>')

resultado_atual = st.session_state.resultado_conciliacao
with st.container(key="results_section"):
    _renderizar_resultado(resultado_atual)

st.html(
    f"""
    <footer class="app-footer">
      <div class="app-brand">
        <span class="brand-mark">{_icone('brand', COR_BRANCO)}</span>
        <span class="brand-copy">
          <strong>concilia</strong>
          <small>Processamento no seu computador</small>
        </span>
      </div>
      <p>Os arquivos são processados localmente e não são enviados para uma
      hospedagem externa.</p>
      <span>Regra de data: 0 dia de tolerância</span>
    </footer>
    """
)
