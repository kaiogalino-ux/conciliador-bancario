"""Camada HTTP do Conciliador Bancário.

Este pacote não contém nenhuma regra de conciliação. Ele apenas recebe os
arquivos por HTTP, grava-os no formato que o pipeline oficial já espera
(uma pasta de ERP + uma pasta de Banco) e chama
`src.web_runner.executar_conciliacao_web`, exatamente como o `main.py` e a
interface Streamlit fazem. Toda a lógica continua em `src/` (ver CLAUDE.md).
"""
