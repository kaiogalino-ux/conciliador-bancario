"""Testes de integração da leitura de extratos bancários em Excel.

Usam arquivos temporários para proteger a detecção do cabeçalho, os nomes
alternativos de colunas, a conversão de datas/valores e os filtros aplicados
por ``ler_banco``. Nenhuma planilha real do projeto é alterada.
"""

from datetime import date

import pytest
from openpyxl import Workbook

from src.leitor_banco import ler_banco


def _criar_excel(caminho, linhas):
    workbook = Workbook()
    planilha = workbook.active
    planilha.title = "Extrato"
    for linha in linhas:
        planilha.append(linha)
    workbook.save(caminho)
    workbook.close()


def test_ler_excel_detecta_cabecalho_e_padroniza_dados(tmp_path, logger_silencioso):
    _criar_excel(
        tmp_path / "extrato.xlsx",
        [
            ["Extrato bancário - Conta 123"],
            ["Período de 01/07/2026 a 31/07/2026"],
            [],
            ["Data", "Valor", "Descrição"],
            ["10/07/2026", "R$ (1.234,56)", "PIX ENVIADO DES: FORNECEDOR ALFA"],
            ["11/07/2026", "R$ 500,00", "PIX RECEBIDO CLIENTE"],
            ["data inválida", "R$ (20,00)", "LINHA INVÁLIDA"],
        ],
    )

    resultado = ler_banco(tmp_path, logger_silencioso)

    assert list(resultado.columns) == ["Data", "Valor", "Favorecido", "Origem"]
    assert len(resultado) == 1
    assert resultado.iloc[0].to_dict() == {
        "Data": date(2026, 7, 10),
        "Valor": -1234.56,
        "Favorecido": "PIX ENVIADO DES: FORNECEDOR ALFA",
        "Origem": "Banco",
    }


def test_ler_excel_aceita_colunas_alternativas_e_filtra_periodo(tmp_path, logger_silencioso):
    _criar_excel(
        tmp_path / "extrato.xlsx",
        [
            ["Data de Compensação", "Valor (R$)", "Histórico"],
            ["30/06/2026", -10.0, "FORA DO PERÍODO"],
            ["01/07/2026", -20.0, "NO LIMITE INICIAL"],
            ["15/07/2026", -30.0, "DENTRO DO PERÍODO"],
            ["31/07/2026", -40.0, "NO LIMITE FINAL"],
            ["01/08/2026", -50.0, "FORA DO PERÍODO"],
        ],
    )

    resultado = ler_banco(
        tmp_path,
        logger_silencioso,
        periodo_inicial=date(2026, 7, 1),
        periodo_final=date(2026, 7, 31),
    )

    assert resultado["Data"].tolist() == [
        date(2026, 7, 1),
        date(2026, 7, 15),
        date(2026, 7, 31),
    ]
    assert resultado["Valor"].tolist() == [-20.0, -30.0, -40.0]
    assert resultado["Favorecido"].tolist() == [
        "NO LIMITE INICIAL",
        "DENTRO DO PERÍODO",
        "NO LIMITE FINAL",
    ]


def test_ler_excel_sem_data_ou_valor_falha_com_mensagem_clara(tmp_path, logger_silencioso):
    _criar_excel(
        tmp_path / "extrato.xlsx",
        [
            ["Relatório bancário"],
            ["Descrição", "Agência"],
            ["PIX ENVIADO", "0001"],
        ],
    )

    with pytest.raises(ValueError, match="cabeçalho reconhecível|colunas de Data e/ou Valor"):
        ler_banco(tmp_path, logger_silencioso)
