# Conciliador Bancário

Automatiza a conciliação entre os lançamentos exportados do sistema ERP
(contas a pagar) e o extrato bancário de 1 banco (OFX ou Excel).

O projeto é dividido em duas metades independentes:

- **`backend/`** — todo o Python: as regras de conciliação, a linha de comando, a interface Streamlit local e a API HTTP. Roda em container Docker.
- **`frontend/`** — a interface web em Next.js, publicada na Vercel. Não executa Python; conversa com o backend por rede.

## Estrutura do projeto

```
backend/
  dados/
    ERP/       -> Excel exportado do ERP (o mais recente é usado automaticamente)
    Banco/     -> Extrato bancário (.ofx, .xlsx ou .xls) (o mais recente é usado automaticamente)
  resultado/
    Resultado.xlsx  -> gerado a cada execução, com 2 abas (ver abaixo)
  logs/
    conciliador_AAAAMMDD.log
  src/
    leitor_erp.py     -> lê o Excel mais recente do ERP e define a Data ERP Usada
    leitor_banco.py   -> lê o extrato mais recente do banco, filtra débitos e período
    conciliador.py    -> toda a lógica de conciliação
    exportador.py     -> gera o Resultado.xlsx
    web_runner.py     -> adaptador entre as interfaces e o pipeline (sem regras próprias)
    utils.py          -> funções auxiliares
    logger.py         -> configuração de logs
  api/
    main.py           -> rotas HTTP (só transporte, nunca regra de conciliação)
    armazenamento.py  -> uploads, validação e limpeza das execuções
  tests/              -> testes automáticos (pytest) que protegem as regras de conciliação
  main.py             -> ponto de entrada da linha de comando
  streamlit_app.py    -> interface local em Streamlit
  streamlit_ui/       -> estilos visuais da interface Streamlit
  Dockerfile
  requirements.txt        -> dependências do servidor (é o que entra no Docker)
  requirements-dev.txt    -> as do servidor + pytest e streamlit
frontend/
  app/                -> páginas e estilos (nenhuma API route)
  lib/api.ts          -> único ponto que fala com o backend
  package.json
docs/                 -> documentação de estado do projeto, regras e histórico de decisões
```

Esta estrutura não deve ser alterada sem autorização — o projeto deve apenas evoluir a partir daqui. As regras completas de negócio estão em [`CLAUDE.md`](CLAUDE.md) e em [`docs/REGRAS_DE_CONCILIACAO.md`](docs/REGRAS_DE_CONCILIACAO.md).

## Instalação

Com o `.venv` ativado, a partir da raiz do projeto:

```powershell
pip install -r backend/requirements-dev.txt   # servidor + testes + Streamlit
cd frontend; npm install
```

## Interface web (Next.js + API)

São dois processos. **Os dois precisam estar rodando.**

1. Backend, numa janela:
   ```powershell
   cd backend
   uvicorn api.main:app --reload
   ```
   Sobe em [http://localhost:8000](http://localhost:8000) (`/health` confirma que está no ar).

2. Frontend, em outra janela:
   ```powershell
   cd frontend
   copy .env.local.example .env.local   # só na primeira vez
   npm run dev
   ```
   Acesse [http://localhost:3000](http://localhost:3000).

3. Selecione o relatório do ERP (`.xlsx`/`.xls`) e o extrato do banco (`.ofx`/`.xlsx`/`.xls`) e clique em **Executar conciliação**. A página mostra os cinco indicadores, a tabela filtrável de pendências e o botão **Baixar planilha final**.

O navegador envia os arquivos **direto** para o backend — por isso o limite de 30 MB por arquivo vale de verdade, sem esbarrar nos limites de request da Vercel.

### Publicação

- **Backend** — Web Service Docker no Render, com `Root Directory = backend`. Variáveis: `CORS_ORIGINS` (a URL do frontend), `API_TOKEN`, `CONCILIADOR_RUNTIME_DIR=/tmp/conciliador-execucoes`, `CONCILIADOR_LOG_DIR=/tmp/conciliador-logs`, mais as variáveis de IA (ver [`backend/.env.example`](backend/.env.example)).
- **Frontend** — projeto na Vercel com `Root Directory = frontend`. Variáveis: `NEXT_PUBLIC_API_URL` (a URL do Render) e `NEXT_PUBLIC_API_TOKEN`.

Testar a imagem antes de publicar:

```powershell
docker build -t conciliador-api ./backend
docker run --rm -p 8000:8000 -e CORS_ORIGINS=http://localhost:3000 conciliador-api
```

> **Sobre o `API_TOKEN`:** ele impede uso casual da API por quem descobrir a URL, mas **não é autenticação de usuário** — como o navegador chama a API diretamente, o token fica visível no JavaScript da página. Para proteção real, é preciso um login.

## Interface Streamlit local

Continua disponível e usa exatamente o mesmo pipeline Python de `main.py` — os
leitores, as regras de conciliação e o exportador não são duplicados na camada
visual.

```powershell
cd backend
python -m streamlit run streamlit_app.py
```

Acesse [http://localhost:8501](http://localhost:8501). Os arquivos enviados
ficam somente na pasta local `.web-runtime/`, que não é versionada.

## Linha de comando

1. **Excel do ERP**: coloque o relatório exportado (`.xlsx` ou `.xls`) dentro de `backend/dados/ERP/`. Se houver mais de um arquivo, o mais recente (por data de modificação) é usado automaticamente.
2. **Extrato do banco**: coloque o arquivo (`.ofx`, `.xlsx` ou `.xls`) dentro de `backend/dados/Banco/`. Da mesma forma, o mais recente é usado.
3. **Rodar a conciliação**, com o `.venv` selecionado como interpretador Python:
   ```powershell
   cd backend
   python main.py
   ```
4. **Resultado**: o arquivo gerado fica em `backend/resultado/Resultado.xlsx`, com 2 abas:
   - **Resumo** — painel executivo com 5 cards (Total na Gestão, Total no Banco, Conciliado, Revisão Manual, Somente no Banco) e a tabela "Itens pendentes de análise".
   - **Base Detalhada** — todos os lançamentos, um por linha, com Status, Tipo Conciliação, Motivo Revisão, ID Lote etc. A conciliação do lote é sempre automática — não há nenhuma aba ou coluna para marcação manual.

   Os logs de cada execução ficam em `backend/logs/`.

## Resumo das regras de conciliação

- A data do ERP usada é a **Data de compensação**; se não estiver preenchida, usa Data de pagamento/baixa/confirmação, sempre linha a linha.
- **Vencimento nunca é usado para conciliar**: ele é preservado apenas para auditoria. Se o lançamento não tiver nenhuma data real de pagamento/compensação, vai para `Revisão Manual` com motivo explícito.
- ERP e banco só conciliam quando estiverem na **mesma data**. A tolerância global é `0 dia`, inclusive para a camada de IA.
- O banco só considera **débitos** (créditos/PIX recebido/depósito são descartados antes de conciliar).
- A comparação de valor é sempre pelo **valor absoluto**.
- Conciliação tenta resolver **individualmente** antes de qualquer agrupamento: par único → duplicidade idêntica → desempate por nome/descrição → duplicidade equivalente (NF diferente, mesmo fornecedor).
- No lado do **banco**, um lançamento claramente identificado como lote NET EMP/EMPR (salário, férias, rescisão ou 13º) fica reservado e nunca participa da conciliação individual. No lado do **ERP**, esses pagamentos tentam primeiro a conciliação individual contra lançamentos bancários comuns, sempre na mesma data e somente quando há nome/descrição forte compatível; o que não encontrar par seguro segue para o fechamento automático do lote.
- PIX/TED/DOC individuais nunca entram na regra de lote.
- **Nunca adivinha**: sem sinal seguro de correspondência, o lançamento fica em Revisão Manual.
- Status possíveis: `Conciliado`, `Revisão Manual`, `Não encontrado no banco`, `Somente banco`.

Detalhes completos (com exemplos) em [`docs/REGRAS_DE_CONCILIACAO.md`](docs/REGRAS_DE_CONCILIACAO.md).

## Testes automáticos

O projeto tem uma suíte de testes (`pytest`) que protege as regras acima contra regressão. Rode antes e depois de qualquer alteração em `backend/src/`:

```powershell
cd backend
pytest
```

Veja [`backend/tests/README_TESTES.md`](backend/tests/README_TESTES.md) para detalhes.
