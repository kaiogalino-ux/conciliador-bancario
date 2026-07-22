# Conciliador Bancário - GestãoClick

Automatiza a conciliação entre os lançamentos exportados do ERP GestãoClick (contas a pagar) e o extrato bancário de 1 banco (OFX ou Excel). Roda pelo terminal/VS Code, sem interface gráfica.

## Estrutura do projeto

```
dados/
  ERP/       -> Excel exportado do GestãoClick (o mais recente é usado automaticamente)
  Banco/     -> Extrato bancário (.ofx, .xlsx ou .xls) (o mais recente é usado automaticamente)
resultado/
  Resultado.xlsx  -> gerado a cada execução, com 3 abas (ver abaixo)
logs/
  conciliador_AAAAMMDD.log
src/
  leitor_erp.py     -> lê o Excel mais recente do ERP e define a Data ERP Usada
  leitor_banco.py   -> lê o extrato mais recente do banco, filtra débitos e período
  conciliador.py    -> toda a lógica de conciliação
  exportador.py     -> gera o Resultado.xlsx
  utils.py          -> funções auxiliares
  logger.py         -> configuração de logs
tests/              -> testes automáticos (pytest) que protegem as regras de conciliação
docs/               -> documentação de estado do projeto, regras e histórico de decisões
main.py             -> ponto de entrada
requirements.txt
```

Esta estrutura não deve ser alterada sem autorização — o projeto deve apenas evoluir a partir daqui. As regras completas de negócio estão em [`CLAUDE.md`](CLAUDE.md) e em [`docs/REGRAS_DE_CONCILIACAO.md`](docs/REGRAS_DE_CONCILIACAO.md).

## Como usar

1. **Excel do GestãoClick**: coloque o relatório exportado (`.xlsx` ou `.xls`) dentro de `dados/ERP/`. Se houver mais de um arquivo, o mais recente (por data de modificação) é usado automaticamente.
2. **Extrato do banco**: coloque o arquivo (`.ofx`, `.xlsx` ou `.xls`) dentro de `dados/Banco/`. Da mesma forma, o mais recente é usado.
3. **Instalar dependências** (uma vez só, com o `.venv` ativado):
   ```
   pip install -r requirements.txt
   ```
4. **Rodar a conciliação**: no VS Code, com o ambiente virtual `.venv` selecionado como interpretador Python, execute:
   ```
   python main.py
   ```
5. **Resultado**: o arquivo gerado fica em `resultado/Resultado.xlsx`, com 3 abas:
   - **Resultado** — todos os lançamentos, um por linha, com Status, Tipo Conciliação, Motivo Revisão, ID Lote etc.
   - **Diagnóstico Revisão Manual** — só os lançamentos em Revisão Manual, agrupados por motivo.
   - **Diagnóstico Lotes NET EMP** — um lote de salário/férias/rescisão por linha, mostrando o resultado de cada tentativa (total direto, combinação exata única, nome/descrição) e o status final. A conciliação do lote é sempre automática — não há nenhuma aba ou coluna para marcação manual.

   Os logs de cada execução ficam em `logs/`.

## Resumo das regras de conciliação

- A data do ERP usada é a **Data de compensação**; se não existir, cai para Data de pagamento/confirmação e, por último, Vencimento — sempre linha a linha.
- O banco só considera **débitos** (créditos/PIX recebido/depósito são descartados antes de conciliar).
- A comparação de valor é sempre pelo **valor absoluto**.
- Conciliação tenta resolver **individualmente** antes de qualquer agrupamento: par único → duplicidade idêntica → desempate por nome/descrição → duplicidade equivalente (NF diferente, mesmo fornecedor).
- Lançamentos "PGTO ... VIA NET EMP/EMPR" (salário, férias, rescisão, 13º) nunca conciliam individualmente — são resolvidos por **lote**, sempre automaticamente: total direto, depois combinação exata única de valores (só quando existe exatamente 1 possível), depois nome/descrição (só se o banco trouxer identificador).
- PIX/TED/DOC individuais nunca entram na regra de lote.
- **Nunca adivinha**: sem sinal seguro de correspondência, o lançamento fica em Revisão Manual.
- Status possíveis: `Conciliado`, `Revisão Manual`, `Não encontrado no banco`, `Somente banco`.

Detalhes completos (com exemplos) em [`docs/REGRAS_DE_CONCILIACAO.md`](docs/REGRAS_DE_CONCILIACAO.md).

## Testes automáticos

O projeto tem uma suíte de testes (`pytest`) que protege as regras acima contra regressão. Rode antes e depois de qualquer alteração em `src/`:

```
pytest
```

Veja [`tests/README_TESTES.md`](tests/README_TESTES.md) para detalhes.

## Dependências

Instale (se ainda não estiverem no `.venv`) com:
```
pip install -r requirements.txt
```
