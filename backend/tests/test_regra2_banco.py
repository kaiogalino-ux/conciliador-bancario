"""Regra 2 (CLAUDE.md): o banco deve considerar somente débitos/saídas.
Créditos, PIX recebido, TED recebida, depósito ou valores positivos nunca
devem entrar na conciliação (logo, nunca podem aparecer como "Somente banco").
A comparação de valor sempre usa o valor absoluto (ERP positivo x Banco
negativo com o mesmo número devem ser considerados o mesmo valor).
"""

from datetime import date

from src.leitor_banco import ler_banco
from tests.conftest import construir_df_banco, construir_df_erp

OFX_MINIMO = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>20260709
<LANGUAGE>POR
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>001
<ACCTID>12345-6
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260501
<DTEND>20260531
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260510
<TRNAMT>-500.00
<FITID>1
<NAME>Fornecedor Teste
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260511
<TRNAMT>1200.00
<FITID>2
<NAME>PIX Recebido Cliente
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260512
<TRNAMT>300.00
<FITID>3
<NAME>TED Recebida Fulano
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260513
<TRNAMT>800.00
<FITID>4
<NAME>Deposito em conta
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1000.00
<DTASOF>20260531
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def test_ler_banco_mantem_so_debitos_e_ignora_creditos(tmp_path, logger_silencioso):
    (tmp_path / "extrato.ofx").write_text(OFX_MINIMO, encoding="utf-8")

    df = ler_banco(tmp_path, logger_silencioso)

    # Só 1 dos 4 lançamentos do OFX é débito (TRNAMT negativo).
    assert len(df) == 1
    assert (df["Valor"] < 0).all()
    assert "PIX Recebido Cliente" not in df["Favorecido"].values
    assert "TED Recebida Fulano" not in df["Favorecido"].values
    assert "Deposito em conta" not in df["Favorecido"].values


def test_creditos_nunca_aparecem_como_somente_banco(tmp_path, logger_silencioso):
    """O filtro acontece em ler_banco, antes da conciliação — então créditos
    nunca chegam a conciliar() e nunca podem virar "Somente banco"."""
    from src.conciliador import STATUS_SOMENTE_BANCO, conciliar

    (tmp_path / "extrato.ofx").write_text(OFX_MINIMO, encoding="utf-8")
    df_banco = ler_banco(tmp_path, logger_silencioso)

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 10), "valor": 999.99, "favorecido": "Lançamento qualquer"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    somente_banco = resultado[resultado["Status"] == STATUS_SOMENTE_BANCO]
    assert "PIX Recebido Cliente" not in somente_banco["Descrição Banco"].values
    assert "TED Recebida Fulano" not in somente_banco["Descrição Banco"].values
    assert "Deposito em conta" not in somente_banco["Descrição Banco"].values


def test_comparacao_usa_valor_absoluto(logger_silencioso):
    """ERP com valor positivo e Banco com o mesmo valor em módulo, mas
    negativo, devem ser considerados o mesmo valor e conciliar."""
    from src.conciliador import STATUS_CONCILIADO, TIPO_VALOR_E_DATA, conciliar

    df_erp = construir_df_erp([
        {"data_usada": date(2026, 5, 15), "valor": 672.08, "favorecido": "Fornecedor Teste"},
    ])
    df_banco = construir_df_banco([
        {"data": date(2026, 5, 15), "valor": -672.08, "favorecido": "PAGTO FORNECEDOR TESTE"},
    ])

    resultado = conciliar(df_erp, df_banco, logger_silencioso)

    assert (resultado["Status"] == STATUS_CONCILIADO).all()
    assert (resultado["Tipo Conciliação"] == TIPO_VALOR_E_DATA).all()
