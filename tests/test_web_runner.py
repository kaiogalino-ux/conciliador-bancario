from datetime import date

import pandas as pd

from src.web_runner import montar_resposta_web


def test_monta_resposta_web_sem_alterar_status_ou_valores():
    resultado = pd.DataFrame(
        [
            {
                "Data ERP Usada": date(2026, 7, 10),
                "Data Banco": date(2026, 7, 10),
                "Valor ERP": 170.0,
                "Valor Banco": -170.0,
                "Favorecido": "Reserva hospedagem",
                "Descrição ERP": "Reserva hospedagem",
                "Descrição Banco": "Reserva hospedagem",
                "Status": "Conciliado",
                "Origem": "ERP+Banco",
                "Motivo Revisão": None,
                "Motivo Não Conciliado": None,
                "Observações": "",
            },
            {
                "Data ERP Usada": date(2026, 7, 11),
                "Data Banco": pd.NaT,
                "Valor ERP": 228.0,
                "Valor Banco": None,
                "Favorecido": "Flash",
                "Descrição ERP": "Flash",
                "Descrição Banco": None,
                "Status": "Revisão Manual",
                "Origem": "ERP",
                "Motivo Revisão": "Duplicidade sem descrição suficiente",
                "Motivo Não Conciliado": None,
                "Observações": "",
            },
            {
                "Data ERP Usada": pd.NaT,
                "Data Banco": date(2026, 7, 12),
                "Valor ERP": None,
                "Valor Banco": -9.8,
                "Favorecido": "Tarifa bancária",
                "Descrição ERP": None,
                "Descrição Banco": "Tarifa bancária",
                "Status": "Somente banco",
                "Origem": "Banco",
                "Motivo Revisão": None,
                "Motivo Não Conciliado": "Nenhum lançamento do ERP corresponde",
                "Observações": "",
            },
        ]
    )

    resposta = montar_resposta_web(
        resultado,
        periodo_inicial=date(2026, 7, 1),
        periodo_final=date(2026, 7, 15),
        total_linhas_erp=2,
        total_linhas_banco=2,
    )

    assert resposta["indicadores"]["totalGestao"] == 398.0
    assert resposta["indicadores"]["totalBanco"] == 179.8
    assert resposta["indicadores"]["conciliado"] == {
        "quantidade": 1,
        "percentual": 33.3,
    }
    assert resposta["indicadores"]["revisaoManual"]["quantidade"] == 1
    assert resposta["indicadores"]["somenteBanco"]["quantidade"] == 1
    assert resposta["pendentesTotal"] == 2
    assert resposta["pendentes"][0]["data"] == "2026-07-11"
    assert resposta["pendentes"][1]["valorBanco"] == 9.8
    assert list(resultado["Status"]) == [
        "Conciliado",
        "Revisão Manual",
        "Somente banco",
    ]
