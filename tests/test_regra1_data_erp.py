"""Regra 1 (CLAUDE.md): se "Data de compensação" estiver preenchida, ela deve
ser usada como Data ERP Usada.

Os testes de `selecionar_data_prioritaria` abaixo continuam passando Vencimento
como um candidato genérico só para provar que a função em si (utils.py) é
neutra — ela escolhe a 1ª série não-nula, qualquer que seja a lista recebida.
A regra de negócio real (2026-07-10, ver docs/HISTORICO_DECISOES.md) — "Vencimento
NUNCA é usado para conciliar" — vive no ponto de chamada, `src/leitor_erp.py`,
que não inclui mais Vencimento nessa lista; os testes `test_ler_erp_*` no fim
deste arquivo protegem isso na integração real (lendo um Excel de verdade).
"""

import pandas as pd

from src.leitor_erp import ler_erp
from src.utils import selecionar_data_prioritaria

ROTULO_COMPENSACAO = "Data de compensação"
ROTULO_VENCIMENTO = "Vencimento"


def test_usa_compensacao_quando_preenchida():
    indice = pd.RangeIndex(2)
    compensacao = pd.Series(pd.to_datetime(["2026-05-10", "2026-05-12"]), index=indice)
    vencimento = pd.Series(pd.to_datetime(["2026-04-01", "2026-04-02"]), index=indice)

    data_escolhida, tipo_escolhido = selecionar_data_prioritaria(
        indice, [(compensacao, ROTULO_COMPENSACAO), (vencimento, ROTULO_VENCIMENTO)]
    )

    assert list(data_escolhida.dt.date.astype(str)) == ["2026-05-10", "2026-05-12"]
    assert list(tipo_escolhido) == [ROTULO_COMPENSACAO, ROTULO_COMPENSACAO]


def test_nunca_usa_vencimento_quando_compensacao_preenchida():
    """Mesmo com as duas datas preenchidas na mesma linha (e diferentes entre
    si), a Data de compensação sempre vence — nunca o Vencimento."""
    indice = pd.RangeIndex(1)
    compensacao = pd.Series(pd.to_datetime(["2026-05-10"]), index=indice)
    vencimento = pd.Series(pd.to_datetime(["2022-01-01"]), index=indice)

    data_escolhida, tipo_escolhido = selecionar_data_prioritaria(
        indice, [(compensacao, ROTULO_COMPENSACAO), (vencimento, ROTULO_VENCIMENTO)]
    )

    assert data_escolhida.dt.date.iloc[0].isoformat() == "2026-05-10"
    assert tipo_escolhido.iloc[0] == ROTULO_COMPENSACAO


def test_usa_vencimento_apenas_quando_compensacao_vazia():
    indice = pd.RangeIndex(2)
    # Linha 0: compensação preenchida. Linha 1: compensação vazia (NaT).
    compensacao = pd.Series(pd.to_datetime(["2026-05-10", pd.NaT]), index=indice)
    vencimento = pd.Series(pd.to_datetime(["2022-01-01", "2026-06-15"]), index=indice)

    data_escolhida, tipo_escolhido = selecionar_data_prioritaria(
        indice, [(compensacao, ROTULO_COMPENSACAO), (vencimento, ROTULO_VENCIMENTO)]
    )

    assert data_escolhida.dt.date.iloc[0].isoformat() == "2026-05-10"
    assert tipo_escolhido.iloc[0] == ROTULO_COMPENSACAO

    assert data_escolhida.dt.date.iloc[1].isoformat() == "2026-06-15"
    assert tipo_escolhido.iloc[1] == ROTULO_VENCIMENTO


def test_prioridade_e_por_linha_nao_global():
    """Se a coluna de compensação existir mas só algumas linhas estiverem
    preenchidas, cada linha decide por si — não é "a coluna inteira existe,
    então usa sempre compensação" nem o contrário."""
    indice = pd.RangeIndex(3)
    compensacao = pd.Series(pd.to_datetime(["2026-05-01", pd.NaT, pd.NaT]), index=indice)
    vencimento = pd.Series(pd.to_datetime(["2020-01-01", "2026-05-02", pd.NaT]), index=indice)

    data_escolhida, tipo_escolhido = selecionar_data_prioritaria(
        indice, [(compensacao, ROTULO_COMPENSACAO), (vencimento, ROTULO_VENCIMENTO)]
    )

    assert tipo_escolhido.iloc[0] == ROTULO_COMPENSACAO
    assert tipo_escolhido.iloc[1] == ROTULO_VENCIMENTO
    assert pd.isna(data_escolhida.iloc[2])
    assert tipo_escolhido.iloc[2] is None


def test_coluna_de_compensacao_ausente_usa_vencimento_como_fallback():
    """Quando o relatório não tem a coluna Data de compensação (série None),
    o Vencimento deve ser usado normalmente como fallback."""
    indice = pd.RangeIndex(1)
    vencimento = pd.Series(pd.to_datetime(["2026-07-01"]), index=indice)

    data_escolhida, tipo_escolhido = selecionar_data_prioritaria(
        indice, [(None, ROTULO_COMPENSACAO), (vencimento, ROTULO_VENCIMENTO)]
    )

    assert data_escolhida.dt.date.iloc[0].isoformat() == "2026-07-01"
    assert tipo_escolhido.iloc[0] == ROTULO_VENCIMENTO


# ---------------------------------------------------------------------------
# Regra revisada em 2026-07-10 (docs/HISTORICO_DECISOES.md): Vencimento nunca
# é usado como Data ERP Usada — testados aqui na integração real de
# `ler_erp()` (lendo um Excel de verdade), não só na função genérica acima.
# ---------------------------------------------------------------------------


def test_ler_erp_usa_confirmacao_nunca_vencimento(tmp_path, logger_silencioso):
    """ERP com Data de confirmação e Vencimento preenchidos: usa confirmação;
    nunca usa vencimento, mesmo que o vencimento seja uma data completamente
    diferente."""
    linhas = [{
        "Data de Confirmação": "10/05/2026",
        "Data de Vencimento": "01/01/2022",
        "Valor": "500,00",
        "Favorecido": "Fornecedor Teste",
    }]
    pd.DataFrame(linhas).to_excel(tmp_path / "relatorio.xlsx", index=False)

    df, _, _ = ler_erp(tmp_path, logger_silencioso)

    assert len(df) == 1
    assert df.iloc[0]["Data ERP Usada"].isoformat() == "2026-05-10"
    assert df.iloc[0]["Tipo Data ERP"] != ROTULO_VENCIMENTO
    # A coluna de auditoria continua preservando o vencimento original.
    assert df.iloc[0]["Vencimento Original"].isoformat() == "2022-01-01"


def test_ler_erp_so_vencimento_nao_gera_data_erp_usada(tmp_path, logger_silencioso):
    """ERP só com Vencimento preenchido (sem compensação/pagamento/confirmação):
    não usa o vencimento — a linha é preservada (não descartada) com Data ERP
    Usada vazia, para virar Revisão Manual em conciliar()."""
    linhas = [{
        "Data de Vencimento": "15/06/2026",
        "Valor": "300,00",
        "Favorecido": "Fornecedor Sem Data De Pagamento",
    }]
    pd.DataFrame(linhas).to_excel(tmp_path / "relatorio.xlsx", index=False)

    df, _, _ = ler_erp(tmp_path, logger_silencioso)

    assert len(df) == 1
    assert pd.isna(df.iloc[0]["Data ERP Usada"])
    assert df.iloc[0]["Vencimento Original"].isoformat() == "2026-06-15"
