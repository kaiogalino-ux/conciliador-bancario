"""Regra 13 (CLAUDE.md, revisada — ver docs/HISTORICO_DECISOES.md): quando o
relatório do ERP tem as colunas "Valor" e "Valor Total" ao mesmo tempo,
"Valor Total" é usada como Valor ERP — ela já inclui juros/multa lançados à
mão num pagamento em atraso, então corresponde ao que de fato saiu do banco.
Sem juros, as duas colunas são iguais e a troca de prioridade não muda nada.
"""

import pandas as pd

from src.leitor_erp import ler_erp


def test_usa_valor_total_quando_ha_juros(tmp_path, logger_silencioso):
    """Pagamento em atraso: "Valor" é o valor original da conta, "Valor Total"
    já inclui a multa/juros lançados manualmente — é esse que bate com o banco."""
    linhas = [{
        "Data de Confirmação": "10/07/2026",
        "Valor": "1000,00",
        "Valor Total": "1050,00",
        "Favorecido": "Fornecedor Com Atraso",
    }]
    pd.DataFrame(linhas).to_excel(tmp_path / "relatorio.xlsx", index=False)

    df, _, _ = ler_erp(tmp_path, logger_silencioso)

    assert len(df) == 1
    assert df.iloc[0]["Valor"] == 1050.00


def test_valor_e_valor_total_iguais_sem_juros(tmp_path, logger_silencioso):
    """Sem atraso, as duas colunas trazem o mesmo valor — a troca de
    prioridade não muda o resultado."""
    linhas = [{
        "Data de Confirmação": "10/07/2026",
        "Valor": "500,00",
        "Valor Total": "500,00",
        "Favorecido": "Fornecedor Em Dia",
    }]
    pd.DataFrame(linhas).to_excel(tmp_path / "relatorio.xlsx", index=False)

    df, _, _ = ler_erp(tmp_path, logger_silencioso)

    assert len(df) == 1
    assert df.iloc[0]["Valor"] == 500.00


def test_usa_valor_como_fallback_quando_nao_ha_valor_total(tmp_path, logger_silencioso):
    """Relatório sem a coluna "Valor Total" (formato antigo/mais simples)
    continua funcionando normalmente, usando "Valor"."""
    linhas = [{
        "Data de Confirmação": "10/07/2026",
        "Valor": "750,00",
        "Favorecido": "Fornecedor Sem Coluna Total",
    }]
    pd.DataFrame(linhas).to_excel(tmp_path / "relatorio.xlsx", index=False)

    df, _, _ = ler_erp(tmp_path, logger_silencioso)

    assert len(df) == 1
    assert df.iloc[0]["Valor"] == 750.00
