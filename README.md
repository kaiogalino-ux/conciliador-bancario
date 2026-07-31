# Conciliador Bancário

Automatiza a conciliação entre os lançamentos exportados do sistema ERP
(contas a pagar) e o extrato bancário de 1 banco (OFX ou Excel).

O projeto é dividido em duas metades independentes:

- **`backend/`** — todo o Python: as regras de conciliação, a linha de comando, a interface Streamlit local e a API HTTP.
- **`frontend/`** — a interface web em Next.js. Não executa Python; conversa com o backend por rede.

> ### ⚠️ Dois modos de execução — saiba em qual você está
>
> O mesmo frontend atende dois modos, e o que muda entre eles é **para onde os arquivos vão**. Quem decide é a variável `NEXT_PUBLIC_API_URL`:
>
> | | `NEXT_PUBLIC_API_URL` | Onde os arquivos são processados |
> |---|---|---|
> | **Modo local** | `http://localhost:8000` (ou `127.0.0.1`) | Neste computador. Nenhum arquivo sai da máquina. |
> | **Modo hospedado** | a URL do backend no Render | Num servidor remoto. Os arquivos **saem** da máquina. |
>
> A página informa o modo ativo no badge do cabeçalho ("Ambiente local" ou "Ambiente hospedado") e na mensagem abaixo do título. Ela nunca afirma processamento local quando a URL configurada é remota.
>
> - **Nunca envie arquivos financeiros para o GitHub.** As pastas `backend/dados/`, `backend/logs/`, `backend/resultado/` e `backend/.web-runtime/` estão no `.gitignore` justamente por isso — mas confira o `git status` antes de qualquer commit.
> - O `backend/.env` contém credenciais reais e também nunca é versionado.
>
> Detalhes de cada modo em [Execução local](#execução-local) e [Execução hospedada](#execução-hospedada-vercel--render).

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
  Dockerfile              -> imagem usada pelo Render no modo hospedado
  requirements.txt        -> só as dependências do servidor
  requirements-dev.txt    -> as do servidor + pytest e streamlit (é o que você instala)
frontend/
  app/                -> páginas e estilos (nenhuma API route)
  lib/api.ts          -> único ponto que fala com o backend
  package.json
docs/                 -> documentação de estado do projeto, regras e histórico de decisões
render.yaml           -> blueprint do backend no Render (modo hospedado)
iniciar_conciliador.ps1 -> sobe backend + frontend e abre o navegador
parar_conciliador.ps1   -> encerra apenas os processos deste projeto
```

Esta estrutura não deve ser alterada sem autorização — o projeto deve apenas evoluir a partir daqui. As regras completas de negócio estão em [`CLAUDE.md`](CLAUDE.md) e em [`docs/REGRAS_DE_CONCILIACAO.md`](docs/REGRAS_DE_CONCILIACAO.md).

## Instalação (uma vez só)

### 1. Python e Node

| | Versão | Onde baixar | Conferir |
|---|---|---|---|
| Python | 3.12 ou superior | [python.org/downloads](https://www.python.org/downloads/) — marque **"Add Python to PATH"** | `python --version` |
| Node.js | 20 LTS ou superior | [nodejs.org](https://nodejs.org/) — versão **LTS** | `node --version` |

### 2. Ambiente virtual do Python

Na raiz do projeto:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

O `.venv` fica **na raiz**, não dentro de `backend/`. Se o PowerShell recusar o `activate`, libere os scripts para o seu usuário:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. Dependências do backend

```powershell
pip install -r backend\requirements-dev.txt
```

O `requirements-dev.txt` traz o servidor, o `pytest` e o Streamlit. O `requirements.txt` (só o servidor) existe para empacotamento e não é o que você usa localmente.

### 4. Dependências do frontend

```powershell
cd frontend
npm install
cd ..
```

### 5. Arquivos de configuração

Nenhum dos dois é versionado — crie-os a partir dos exemplos:

```powershell
copy backend\.env.example backend\.env
copy frontend\.env.local.example frontend\.env.local
```

**`backend\.env`** — para uso local, basta:

```ini
CORS_ORIGINS=http://localhost:3000
API_TOKEN=
IA_MODO=DESATIVADA
GROQ_API_KEY=
```

- `API_TOKEN` vazio deixa a API aberta. É aceitável aqui porque ela só escuta em `127.0.0.1`.
- `IA_MODO=DESATIVADA` é o padrão. Para ligar a camada de IA, use `SOMBRA` ou `AUTOMATICO` e preencha `GROQ_API_KEY` (ver [`backend/.env.example`](backend/.env.example)).

**`frontend\.env.local`**:

```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_TOKEN=
```

> Tudo que começa com `NEXT_PUBLIC_` vai para o JavaScript enviado ao navegador e é visível. Nunca coloque um segredo real ali.

## Execução local

Este é o modo em que **nenhum arquivo sai do computador**: os dois servidores escutam somente em `127.0.0.1`, e o computador precisa **permanecer ligado** com as janelas **abertas** durante o uso. Ao fechar as janelas, o sistema para de responder.

### Modo simples (recomendado)

Na raiz do projeto:

```powershell
.\iniciar_conciliador.ps1
```

O script confere o ambiente, abre uma janela para cada servidor, espera os dois responderem e abre o navegador. Use `-SemNavegador` para não abrir a aba automaticamente.

### Modo manual

Dois processos, **os dois precisam estar rodando**, cada um na sua janela:

```powershell
# janela 1 - backend
cd backend
..\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# janela 2 - frontend
cd frontend
npm run dev
```

| Serviço | Endereço |
|---|---|
| Interface | [http://localhost:3000](http://localhost:3000) |
| API | [http://localhost:8000](http://localhost:8000) |
| Saúde da API | [http://localhost:8000/health](http://localhost:8000/health) |
| Documentação da API | [http://localhost:8000/docs](http://localhost:8000/docs) |

Na interface, selecione o relatório do ERP (`.xlsx`/`.xls`) e o extrato do banco (`.ofx`/`.xlsx`/`.xls`), até 30 MB cada, e clique em **Executar conciliação**. A página mostra os cinco indicadores, a tabela filtrável de pendências e o botão **Baixar planilha final**.

O navegador envia os arquivos **direto** para o backend — não há proxy no Next.js.

## Como parar

```powershell
.\parar_conciliador.ps1
```

O script encerra **apenas** os processos deste projeto, identificados pelos PIDs registrados na inicialização e por quem está escutando nas portas 8000 e 3000 — sempre conferindo antes que o processo pertence a esta pasta. Um servidor de outra pessoa na mesma porta é reportado, nunca encerrado. Nenhum `taskkill /IM python.exe` ou `/IM node.exe` é usado.

Fechar as duas janelas dos servidores também funciona.

## Execução hospedada (Vercel + Render)

Versão hospedada, acessível pela internet, sem depender de nenhum servidor aberto na sua máquina. São dois serviços, porque a Vercel não executa Python:

| Metade | Host | O que roda | Configuração |
|---|---|---|---|
| `frontend/` | **Vercel** | só HTML/JS estático — o `next build` não gera nenhuma função | Root Directory `frontend` |
| `backend/` | **Render** | a API HTTP em container Docker | [`render.yaml`](render.yaml), contexto `backend/` |

O navegador chama a API do Render **direto**, sem proxy na Vercel (decisão registrada em [`docs/HISTORICO_DECISOES.md`](docs/HISTORICO_DECISOES.md)) — por isso o limite de 4,5 MB por request e o timeout de função da Vercel não se aplicam aos arquivos.

### Variáveis que ligam os dois lados

Os quatro valores têm que ser coerentes entre si, ou o navegador bloqueia a chamada no CORS:

| Onde | Variável | Valor |
|---|---|---|
| Vercel | `NEXT_PUBLIC_API_URL` | a URL pública do serviço no Render |
| Vercel | `NEXT_PUBLIC_API_TOKEN` | o mesmo valor de `API_TOKEN` |
| Render | `CORS_ORIGINS` | o domínio da Vercel (ex.: `https://seu-app.vercel.app`) |
| Render | `API_TOKEN` | token compartilhado, igual ao do frontend |

`NEXT_PUBLIC_API_URL` é lida **no build**, não em runtime: depois de alterá-la é preciso republicar o frontend para o valor novo valer.

### O que muda para quem usa

- **Os arquivos são enviados ao backend.** No modo hospedado, o ERP e o extrato saem do seu computador e são processados no servidor do Render. A interface avisa isso no badge "Ambiente hospedado" e na mensagem "Modo hospedado".
- **Baixe o `Resultado.xlsx` ao final de cada execução.** O ERP e o extrato são apagados do servidor assim que a conciliação termina; só o resultado fica, e apenas até a limpeza das execuções antigas. Não existe histórico no servidor — se você fechar a aba sem baixar, a execução se perde e é preciso rodar de novo.
- **Como ainda não há autenticação individual (ver abaixo), use apenas arquivos sintéticos ou previamente autorizados.**

### Autenticação: o que existe hoje

**Não existe autenticação individual.** Não há login, usuário nem senha, e nenhuma separação por pessoa: qualquer um que tenha a URL e o token consegue rodar uma conciliação.

O `API_TOKEN` é um **token compartilhado**, único para todos. Ele serve para barrar uso casual da URL pública — não identifica quem enviou o quê. Como o frontend precisa dele no navegador, ele vai no JavaScript como `NEXT_PUBLIC_API_TOKEN` e **é visível** para qualquer pessoa que abra o código da página.

É exatamente por isso que a recomendação de arquivos sintéticos vale enquanto a hospedagem estiver nesta fase.

### Limitações do plano gratuito do Render

O [`render.yaml`](render.yaml) usa `plan: free`, que tem dois limites relevantes:

- **Hibernação:** o serviço dorme após ~15 minutos sem uso. A primeira conciliação depois disso espera o container subir (na ordem de ~50s) antes de começar. Não é erro — é cold start.
- **512 MB de RAM:** a conciliação carrega as duas planilhas com `pandas` e gera o `.xlsx` com `openpyxl`. A interface aceita até 30 MB por arquivo, e um par de arquivos grandes pode estourar esse limite e derrubar o container no meio da execução. Se isso acontecer com os seus relatórios reais, o caminho é um plano pago — não há ajuste de regra que resolva.

Há ainda um limite de horas de execução por mês no free tier, que a hibernação ajuda a economizar.

## Testes automáticos

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

Ou, da raiz, `.venv\Scripts\python.exe -m pytest backend/tests` (é o que o VS Code usa, já configurado em [`.vscode/settings.json`](.vscode/settings.json)).

Rode antes e depois de qualquer alteração em `backend/src/`. Detalhes em [`backend/tests/README_TESTES.md`](backend/tests/README_TESTES.md).

## Interface Streamlit

Continua disponível e usa **exatamente o mesmo pipeline** da API — os leitores, as regras de conciliação e o exportador não são duplicados na camada visual. Serve como conferência independente do resultado.

```powershell
cd backend
..\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Acesse [http://localhost:8501](http://localhost:8501). Os arquivos enviados ficam somente em `backend/.web-runtime/`, que não é versionada.

O `parar_conciliador.ps1` **não** encerra o Streamlit (ele usa a porta 8501, fora do par 8000/3000) — feche a janela dele quando terminar.

## Comparar Streamlit e API

As duas interfaces chamam a mesma função (`executar_conciliacao_web`), então devem produzir resultado idêntico. Para conferir com os mesmos arquivos:

1. Rode a conciliação na interface web e baixe o `Resultado.xlsx`.
2. Rode a mesma conciliação no Streamlit e baixe o `Resultado.xlsx`.
3. Compare **o conteúdo**, não o tamanho nem os bytes do arquivo: dois `.xlsx` gerados em minutos diferentes divergem no carimbo "Gerado em..." do rodapé e nos metadados do zip, mesmo com dados idênticos.

O que precisa bater: total de registros, conciliados, revisão manual, somente banco, somente ERP, valores, datas, favorecidos, motivos de revisão, tipo de conciliação e as duas abas do `Resultado.xlsx`.

Se divergir, **não altere as regras** para forçar igualdade — identifique primeiro em qual camada está a diferença (upload, leitura, serialização, exportação ou interface). A lógica oficial em `backend/src/` é a referência.

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

## Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `A porta 8000 já está em uso` ao iniciar | Um servidor anterior ficou de pé | `.\parar_conciliador.ps1` e tente de novo |
| A interface abre mas dá erro ao conciliar | O backend não está rodando | Abra [http://localhost:8000/health](http://localhost:8000/health); deve responder `{"status":"ok"}` |
| `Não foi possível falar com o servidor de conciliação` | `NEXT_PUBLIC_API_URL` errado, ou backend fora do ar | Confira o `frontend\.env.local` e reinicie o `npm run dev` (variáveis `NEXT_PUBLIC_` só são lidas na inicialização) |
| O VS Code marca `fastapi` como não encontrado | Interpretador errado selecionado | *Python: Select Interpreter* → o `.venv` da raiz |
| `next dev` sobe na porta 3001 | Já existe outro Next rodando na 3000 | `.\parar_conciliador.ps1` antes de iniciar |
