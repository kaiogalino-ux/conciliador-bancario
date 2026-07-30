import os
import time

from src.utils import encontrar_arquivo_mais_recente


def test_ignora_arquivo_temporario_do_excel(tmp_path):
    arquivo_valido = tmp_path / "relatorio.xlsx"
    arquivo_temporario = tmp_path / "~$relatorio.xlsx"

    arquivo_valido.write_bytes(b"arquivo valido")
    arquivo_temporario.write_bytes(b"arquivo temporario")

    agora = time.time()
    os.utime(arquivo_valido, (agora - 10, agora - 10))
    os.utime(arquivo_temporario, (agora, agora))

    encontrado = encontrar_arquivo_mais_recente(
        tmp_path,
        (".xlsx",),
    )

    assert encontrado == arquivo_valido


def test_ignora_arquivo_vazio(tmp_path):
    arquivo_valido = tmp_path / "relatorio.xlsx"
    arquivo_vazio = tmp_path / "relatorio_novo.xlsx"

    arquivo_valido.write_bytes(b"arquivo valido")
    arquivo_vazio.write_bytes(b"")

    agora = time.time()
    os.utime(arquivo_valido, (agora - 10, agora - 10))
    os.utime(arquivo_vazio, (agora, agora))

    encontrado = encontrar_arquivo_mais_recente(
        tmp_path,
        (".xlsx",),
    )

    assert encontrado == arquivo_valido
