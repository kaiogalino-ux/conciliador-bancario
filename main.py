"""Ponto de entrada do Conciliador Bancário - GestãoClick.

Fluxo:
1. Lê o Excel mais recente em dados/ERP.
2. Lê o extrato mais recente (OFX ou Excel) em dados/Banco.
3. Concilia os lançamentos comparando somente Valor e Data.
4. Exporta o resultado para resultado/Resultado.xlsx.
"""

from pathlib import Path

from src.conciliador import conciliar
from src.exportador import exportar_resultado
from src.ia_config import carregar_configuracao_ia
from src.leitor_banco import ler_banco
from src.leitor_erp import ler_erp
from src.logger import obter_logger

PASTA_BASE = Path(__file__).resolve().parent
PASTA_ERP = PASTA_BASE / "dados" / "ERP"
PASTA_BANCO = PASTA_BASE / "dados" / "Banco"
ARQUIVO_RESULTADO = PASTA_BASE / "resultado" / "Resultado.xlsx"


def main() -> None:
    logger = obter_logger()
    logger.info("Iniciando conciliação bancária.")

    try:
        df_erp, periodo_inicial, periodo_final = ler_erp(PASTA_ERP, logger)
        df_banco = ler_banco(PASTA_BANCO, logger, periodo_inicial, periodo_final)
        # Camada de IA (2ª etapa decisiva) — controlada só por variável de
        # ambiente (IA_MODO=DESATIVADA/SOMBRA/AUTOMATICO, ver .env.example e
        # src/ia_config.py). Sem configuração, comporta-se exatamente como
        # antes dessa funcionalidade existir.
        config_ia = carregar_configuracao_ia(logger)
        resultado = conciliar(df_erp, df_banco, logger, config_ia=config_ia)
        exportar_resultado(
            resultado, ARQUIVO_RESULTADO, logger,
            periodo_inicial=periodo_inicial, periodo_final=periodo_final,
        )
    except Exception:
        logger.exception("Falha ao executar a conciliação.")
        raise

    logger.info("Conciliação concluída com sucesso.")


if __name__ == "__main__":
    main()
