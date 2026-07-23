"""Interface web (Streamlit) para upload dos arquivos e execução da conciliação.

Orquestra o mesmo pipeline de main.py (ler_erp -> ler_banco -> conciliar ->
exportar_resultado) por cima de uma tela de upload/execução — nenhuma regra de
negócio de src/ é alterada ou duplicada aqui. Rodar com:

    streamlit run app.py
"""

import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from src.conciliador import conciliar
from src.exportador import exportar_resultado
from src.ia_config import carregar_configuracao_ia
from src.leitor_banco import EXTENSOES_BANCO, ler_banco
from src.leitor_erp import ler_erp
from src.logger import obter_logger
from src.utils import EXTENSOES_EXCEL, encontrar_arquivo_mais_recente

PASTA_BASE = Path(__file__).resolve().parent
PASTA_ERP = PASTA_BASE / "dados" / "ERP"
PASTA_BANCO = PASTA_BASE / "dados" / "Banco"
ARQUIVO_RESULTADO = PASTA_BASE / "resultado" / "Resultado.xlsx"

PASTA_ERP.mkdir(parents=True, exist_ok=True)
PASTA_BANCO.mkdir(parents=True, exist_ok=True)

STATUS_CORES = {
    "Conciliado": "#15803D",
    "Revisão Manual": "#D97706",
    "Não encontrado no banco": "#DC2626",
    "Somente banco": "#3B82F6",
}

st.set_page_config(page_title="Conciliador Bancário", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@400;500;600;700&display=swap');

    :root {
        --color-primary: #1E40AF;
        --color-on-primary: #FFFFFF;
        --color-secondary: #3B82F6;
        --color-accent: #D97706;
        --color-background: #F8FAFC;
        --color-foreground: #1E3A8A;
        --color-muted: #E9EEF6;
        --color-border: #DBEAFE;
        --color-destructive: #DC2626;
    }

    html, body, [class*="css"] { font-family: 'Fira Sans', sans-serif; }
    .stDataFrame, .stDataFrame * { font-family: 'Fira Code', monospace !important; }

    .cb-header {
        display: flex; align-items: center; gap: 0.75rem;
        margin-bottom: 0.25rem;
    }
    .cb-header svg { flex-shrink: 0; }
    .cb-header h1 {
        font-size: 1.6rem; font-weight: 700; color: var(--color-foreground); margin: 0;
    }
    .cb-subtitle { color: #64748B; margin-bottom: 1.5rem; }

    .cb-upload-card {
        border: 1px solid var(--color-border);
        border-radius: 12px;
        padding: 1.25rem 1.25rem 1rem 1.25rem;
        background: var(--color-muted);
        margin-bottom: 0.5rem;
    }
    .cb-upload-card h3 {
        display: flex; align-items: center; gap: 0.5rem;
        font-size: 1rem; color: var(--color-foreground); margin: 0 0 0.5rem 0;
    }
    .cb-current-file {
        font-size: 0.85rem; color: #475569; margin-top: 0.5rem;
        display: flex; align-items: center; gap: 0.4rem;
    }

    .stButton > button[kind="primary"] {
        background-color: var(--color-primary);
        border-color: var(--color-primary);
        transition: background-color 150ms ease, transform 150ms ease;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #1E3A8A;
        transform: translateY(-1px);
    }

    .cb-badge {
        display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; color: #FFFFFF;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

ICONE_BANCO = """<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1E40AF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V9l7-6 7 6v12"/><path d="M9 21v-6h6v6"/></svg>"""
ICONE_UPLOAD = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>"""
ICONE_ARQUIVO = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>"""

st.markdown(
    f"""
    <div class="cb-header">{ICONE_BANCO}<h1>Conciliador Bancário</h1></div>
    <div class="cb-subtitle">GestãoClick × extrato bancário — envie os dois arquivos e rode a conciliação.</div>
    """,
    unsafe_allow_html=True,
)


class _HandlerDeMemoria(logging.Handler):
    """Captura as mensagens de log da execução atual para exibir na tela."""

    def __init__(self):
        super().__init__()
        self.linhas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.linhas.append(self.format(record))


def _arquivo_atual(pasta: Path, extensoes: tuple[str, ...]):
    return encontrar_arquivo_mais_recente(pasta, extensoes)


def _salvar_upload(arquivo_subido, pasta_destino: Path) -> None:
    caminho = pasta_destino / arquivo_subido.name
    caminho.write_bytes(arquivo_subido.getbuffer())


col_erp, col_banco = st.columns(2, gap="large")

with col_erp:
    st.markdown(
        f'<div class="cb-upload-card"><h3>{ICONE_UPLOAD} Excel do ERP (GestãoClick)</h3>',
        unsafe_allow_html=True,
    )
    upload_erp = st.file_uploader(
        "Excel do ERP", type=["xlsx", "xls"], label_visibility="collapsed", key="upload_erp"
    )
    if upload_erp is not None:
        _salvar_upload(upload_erp, PASTA_ERP)
    arquivo_erp_atual = _arquivo_atual(PASTA_ERP, EXTENSOES_EXCEL)
    if arquivo_erp_atual:
        st.markdown(
            f'<div class="cb-current-file">{ICONE_ARQUIVO} Arquivo que será usado: <strong>{arquivo_erp_atual.name}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="cb-current-file">Nenhum arquivo em dados/ERP ainda.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with col_banco:
    st.markdown(
        f'<div class="cb-upload-card"><h3>{ICONE_UPLOAD} Extrato do banco (.ofx ou Excel)</h3>',
        unsafe_allow_html=True,
    )
    upload_banco = st.file_uploader(
        "Extrato do banco", type=["ofx", "xlsx", "xls"], label_visibility="collapsed", key="upload_banco"
    )
    if upload_banco is not None:
        _salvar_upload(upload_banco, PASTA_BANCO)
    arquivo_banco_atual = _arquivo_atual(PASTA_BANCO, EXTENSOES_BANCO)
    if arquivo_banco_atual:
        st.markdown(
            f'<div class="cb-current-file">{ICONE_ARQUIVO} Arquivo que será usado: <strong>{arquivo_banco_atual.name}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="cb-current-file">Nenhum arquivo em dados/Banco ainda.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

st.write("")
pode_conciliar = arquivo_erp_atual is not None and arquivo_banco_atual is not None
botao = st.button("Conciliar", type="primary", disabled=not pode_conciliar, use_container_width=False)
if not pode_conciliar:
    st.caption("Envie o Excel do ERP e o extrato do banco para habilitar a conciliação.")

if botao:
    logger = obter_logger()
    handler_memoria = _HandlerDeMemoria()
    handler_memoria.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler_memoria)

    resultado_df = None
    try:
        with st.status("Rodando conciliação...", expanded=True) as status:
            status.write("Lendo Excel do ERP...")
            df_erp, periodo_inicial, periodo_final = ler_erp(PASTA_ERP, logger)

            status.write("Lendo extrato do banco...")
            df_banco = ler_banco(PASTA_BANCO, logger, periodo_inicial, periodo_final)

            status.write("Conciliando lançamentos...")
            config_ia = carregar_configuracao_ia(logger)
            resultado_df = conciliar(df_erp, df_banco, logger, config_ia=config_ia)

            status.write("Gerando Resultado.xlsx...")
            exportar_resultado(resultado_df, ARQUIVO_RESULTADO, logger)

            status.update(label="Conciliação concluída.", state="complete", expanded=False)
    except Exception as erro:
        st.error(f"Falha ao executar a conciliação: {erro}")
    finally:
        logger.removeHandler(handler_memoria)

    if resultado_df is not None:
        st.success("Resultado.xlsx gerado com sucesso.")

        contagem_status = resultado_df["Status"].value_counts()
        colunas_metricas = st.columns(4)
        for coluna, status_nome in zip(colunas_metricas, STATUS_CORES.keys()):
            coluna.metric(status_nome, int(contagem_status.get(status_nome, 0)))

        with open(ARQUIVO_RESULTADO, "rb") as arquivo:
            st.download_button(
                "Baixar Resultado.xlsx",
                data=arquivo.read(),
                file_name="Resultado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

        st.write("")
        filtro_status = st.multiselect(
            "Filtrar por Status", options=list(STATUS_CORES.keys()), default=list(STATUS_CORES.keys())
        )
        tabela = resultado_df[resultado_df["Status"].isin(filtro_status)] if filtro_status else resultado_df
        st.dataframe(tabela, use_container_width=True, height=480)

        with st.expander("Log da execução"):
            st.code("\n".join(handler_memoria.linhas), language=None)
