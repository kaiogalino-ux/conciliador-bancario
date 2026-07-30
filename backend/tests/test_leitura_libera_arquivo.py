"""Garante que ler uma planilha não deixa o arquivo bloqueado.

No Windows, um handle aberto impede a exclusão do arquivo. A interface web
apaga os arquivos enviados assim que a conciliação termina (ver
`api/armazenamento.py`), então qualquer leitor que não feche o que abriu
quebra essa limpeza — inclusive no caminho de erro.

Estes testes exercitam a exclusão imediatamente após a leitura, que é o
cenário exato que falhava antes de `ler_tabela_com_cabecalho_detectado` passar
a usar `with pd.ExcelFile(...)`.
"""

import logging

import pandas as pd
import pytest

from src.leitor_banco import ler_banco
from src.leitor_erp import ler_erp
from src.utils import ler_tabela_com_cabecalho_detectado


@pytest.fixture
def logger_silencioso() -> logging.Logger:
    logger = logging.getLogger("tests.leitura_libera_arquivo")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def _planilha(caminho, linhas) -> None:
    pd.DataFrame(linhas).to_excel(caminho, index=False)


def test_arquivo_pode_ser_apagado_logo_apos_a_leitura(tmp_path, logger_silencioso):
    caminho = tmp_path / "relatorio.xlsx"
    _planilha(caminho, [{"Data": "10/07/2026", "Valor": 170.0, "Favorecido": "Fornecedor"}])

    df, nome_aba, _ = ler_tabela_com_cabecalho_detectado(caminho, logger_silencioso)

    # Sem o `with`, este unlink levantava PermissionError no Windows.
    caminho.unlink()

    assert not caminho.exists()
    assert len(df) == 1
    assert nome_aba


def test_arquivo_e_liberado_mesmo_quando_a_leitura_falha(tmp_path, logger_silencioso):
    caminho = tmp_path / "sem_cabecalho.xlsx"
    # Nenhuma coluna reconhecível: a leitura precisa terminar em ValueError.
    _planilha(caminho, [{"aaa": 1, "bbb": 2}, {"aaa": 3, "bbb": 4}])

    with pytest.raises(ValueError):
        ler_tabela_com_cabecalho_detectado(caminho, logger_silencioso)

    # O caminho de erro também precisa fechar o arquivo — era ele que deixava
    # o upload inválido preso no disco.
    caminho.unlink()
    assert not caminho.exists()


def test_pasta_do_erp_pode_ser_removida_apos_ler_erp(tmp_path, logger_silencioso):
    import shutil

    pasta = tmp_path / "erp"
    pasta.mkdir()
    _planilha(
        pasta / "gestao.xlsx",
        [{"Data de Confirmacao": "10/07/2026", "Valor": 170.0, "Favorecido": "Fornecedor"}],
    )

    ler_erp(pasta, logger_silencioso)

    shutil.rmtree(pasta)
    assert not pasta.exists()


def test_pasta_do_banco_pode_ser_removida_apos_ler_banco(tmp_path, logger_silencioso):
    import shutil

    pasta = tmp_path / "banco"
    pasta.mkdir()
    _planilha(
        pasta / "extrato.xlsx",
        [{"Data": "10/07/2026", "Valor": -170.0, "Historico": "Fornecedor"}],
    )

    ler_banco(pasta, logger_silencioso)

    shutil.rmtree(pasta)
    assert not pasta.exists()
