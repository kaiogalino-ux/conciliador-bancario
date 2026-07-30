# Prompt de contexto — Conciliador Bancário (GestãoClick)

> Cole este prompt no início de qualquer conversa com uma IA (Claude, ChatGPT etc.) para dar contexto completo sobre o projeto antes de pedir qualquer alteração, dúvida ou nova funcionalidade.

## O que é o projeto

Sou dono de uma empresa que usa o ERP **GestãoClick**. Tenho um projeto em Python chamado **Conciliador Bancário** que automatiza a conciliação entre:

- os lançamentos de **contas a pagar** exportados do GestãoClick (Excel); e
- o **extrato bancário** de 1 banco (arquivo `.ofx` ou Excel).

O objetivo é dizer, para cada lançamento, se ele foi pago (`Conciliado`), se precisa de revisão humana (`Revisão Manual`), se está no ERP mas não apareceu no banco (`Não encontrado no banco`), ou se apareceu no banco mas não no ERP (`Somente banco`).

Roda por terminal/VS Code (`cd backend && python main.py`) e também por duas interfaces web locais (Streamlit e Next.js + FastAPI). Não é um produto para terceiros — é uma ferramenta interna meu/minha equipe usa para fechar a conciliação bancária mensal sem fazer isso manualmente linha a linha numa planilha.

## Stack técnica

- Python puro + **pandas** e **openpyxl** para ler/escrever Excel.
- **ofxparse** para ler extratos `.ofx` (com fallback de encoding: utf-8-sig, utf-8, cp1252, latin-1, iso-8859-1).
- **pytest** para a suíte de testes que protege as regras de negócio.
- **Groq API** (SDK `groq`, modelo `openai/gpt-oss-120b`) como camada opcional de IA para casos ambíguos — desligada por padrão.
- `python-dotenv` para configuração via `.env` (nunca commitado — só `.env.example`).
- **FastAPI + uvicorn** expondo o pipeline por HTTP, e **Next.js/React** como interface web. Sem banco de dados. Entrada = arquivos enviados (ou em pastas, no modo terminal); saída = um `.xlsx`.

## Estrutura de pastas

```
Conciliador_Bancario/
├── backend/                  -> todo o Python
│   ├── dados/
│   │   ├── ERP/     -> Excel exportado do GestãoClick (o mais recente por data de modificação é usado automaticamente)
│   │   └── Banco/   -> extrato do banco (.ofx, .xlsx ou .xls) (idem, o mais recente é usado)
│   ├── resultado/
│   │   └── Resultado.xlsx  -> gerado a cada execução, com as abas "Resumo" e "Base Detalhada"
│   ├── logs/
│   │   └── conciliador_AAAAMMDD.log
│   ├── src/
│   │   ├── leitor_erp.py     -> lê o Excel do ERP, define "Data ERP Usada" linha a linha
│   │   ├── leitor_banco.py   -> lê o extrato do banco, filtra débitos e período
│   │   ├── conciliador.py    -> TODA a lógica de conciliação (o coração do projeto)
│   │   ├── exportador.py     -> gera o Resultado.xlsx
│   │   ├── web_runner.py     -> adaptador entre as interfaces e o pipeline (sem regras próprias)
│   │   ├── utils.py          -> normalização de texto, detecção de colunas/cabeçalho, período do relatório
│   │   ├── logger.py         -> configuração de logs
│   │   ├── ia_config.py      -> config da camada de IA, lida só de variável de ambiente
│   │   ├── ia_revisor.py     -> lógica pura (sem rede) da IA: elegibilidade, seleção, revalidação, conflitos
│   │   └── ia_cliente_groq.py -> único módulo que fala com a API da Groq (isolado — o resto funciona sem `groq` instalado)
│   ├── api/      -> camada HTTP (FastAPI). Só transporte, nunca regra de conciliação
│   ├── tests/    -> pytest, protege as regras contra regressão
│   ├── main.py
│   ├── streamlit_app.py   -> interface Streamlit local
│   ├── requirements.txt        -> só as dependências do servidor
│   └── requirements-dev.txt    -> as do servidor + pytest e streamlit
├── frontend/                 -> interface web Next.js (sem nenhuma API route)
├── docs/     -> REGRAS_DE_CONCILIACAO.md e HISTORICO_DECISOES.md (histórico de todas as decisões de regra)
├── README.md
└── CLAUDE.md  -> fonte da verdade de TODAS as regras de negócio (o que está resumido aqui vem de lá)
```

**Regra de ouro: essa estrutura não deve ser alterada sem autorização explícita minha.** O projeto evolui a partir daqui, nunca é recriado do zero.

## Como funciona (fluxo do `backend/main.py`)

1. Lê o Excel mais recente de `backend/dados/ERP/`.
2. Lê o extrato mais recente de `backend/dados/Banco/`.
3. Roda a conciliação (`backend/src/conciliador.py`), com a camada de IA opcional por cima.
4. Exporta `backend/resultado/Resultado.xlsx`.

Para rodar: ativar o `.venv` (na raiz), `pip install -r backend/requirements-dev.txt`, depois `cd backend && python main.py` (interpretador `.venv` selecionado no VS Code).

As interfaces web executam **exatamente esse mesmo pipeline**, através de `backend/src/web_runner.py` — nenhuma regra é duplicada nelas. Ver `README.md` para os comandos.

## Regras de negócio (resumo — o detalhe completo está em `CLAUDE.md` e `docs/REGRAS_DE_CONCILIACAO.md`)

### Data usada do ERP
- Prioridade linha a linha: **Data de compensação** → **Data de pagamento/baixa/confirmação**.
- **Vencimento NUNCA é usado** para conciliar (decisão de 2026-07-10). Uma linha só com vencimento fica com "Data ERP Usada" vazia e vai direto para Revisão Manual, sem tentar casar com o banco.

### Banco
- Só entram **débitos**. Créditos, PIX recebido, depósito etc. são descartados antes de qualquer coisa — nunca aparecem no resultado.
- Comparação de valor é sempre por **valor absoluto**.
- Lançamentos fora do período do ERP são ignorados e logados.

### Ordem de conciliação (nunca pula etapa, nunca adivinha)
1. Separar lotes claros **NET EMP/EMPR** (salário, férias, rescisão, 13º) — nunca entram na conciliação individual.
2. Conciliação individual: par único (valor + data) → duplicidade idêntica → desempate por nome/descrição → duplicidade equivalente (NF diferente, mesmo fornecedor).
3. Tolerância de data de **1 dia** só para pagamentos individuais (nunca lote), e só com nome/descrição forte compatível.
4. Lote NET EMP/EMPR: sempre automático, data EXATA (sem tolerância), 3 etapas em ordem — total direto → combinação exata única (subset sum, até 40 candidatos) → nome/descrição (só se o banco trouxer identificador). Se nenhuma etapa fechar com segurança, todo o grupo vai para Revisão Manual com motivo específico.
5. Verificação final de recuperação de "Não encontrado no banco" (só depois de tudo, nunca interfere nas fases anteriores).
6. Consolidação: cada par ERP×Banco vira **uma única linha** (`Origem = "ERP+Banco"`), nunca duas linhas espelhadas.

### Regras especiais importantes
- "FGTS" nunca é tratado como lote NET EMP, mesmo contendo "RESCISÃO" ou "13" no texto (vai direto para a Caixa, nunca junto da folha).
- PIX/TED/DOC individuais com nome específico nunca entram na regra de lote, mesmo se houver vários no mesmo dia.
- **Nunca cria exceção por fornecedor específico.** Toda correção é na regra geral (ex.: nunca "se fornecedor for X, faça Y").
- **Não existe conciliação manual do lote** — é sempre 100% automático baseado em evidência matemática ou de nome.

### Status possíveis (só estes 4)
`Conciliado`, `Revisão Manual`, `Não encontrado no banco`, `Somente banco`.

### Resultado.xlsx
Duas abas, "Resumo" (painel executivo de 5 cards + itens pendentes) e "Base Detalhada" (um lançamento por linha). Não existem abas de diagnóstico separadas — tudo virou coluna: Motivo Não Conciliado, Possível Data/Valor/Descrição Banco, Status do Possível Banco etc. Colunas obrigatórias incluem Data ERP Usada, Tipo Data ERP, Data Banco, Valor ERP, Valor Banco, Favorecido, Status, Tipo Conciliação, Motivo Revisão, ID Lote, Origem, entre outras (lista completa em `CLAUDE.md`).

## Camada de IA (opcional, desligada por padrão)

- Só analisa o que sobrar em `Revisão Manual` **depois** de todas as regras determinísticas — nunca desfaz uma conciliação já feita.
- Controlada só por `.env` / `IA_MODO`: `DESATIVADA` (default, sem colunas extras) | `SOMBRA` (roda e registra o que faria, mas não altera Status) | `AUTOMATICO` (concilia sozinha se aprovada em todas as revalidações).
- Provedor: Groq (`openai/gpt-oss-120b`), Structured Outputs `strict=true`. Sem `GROQ_API_KEY`/`GROQ_MODEL`, a camada é desativada automaticamente (nunca derruba a execução).
- Elegibilidade restrita (lista branca de motivos), nunca lote NET EMP, nunca reaproveita banco já consumido, nunca deixa dois ERPs escolherem o mesmo candidato bancário.

## Testes

Suíte `pytest` em `backend/tests/` protege todas as regras acima com dados sintéticos (não depende dos arquivos reais em `backend/dados/`). **Sempre rodar `cd backend && pytest` antes e depois de qualquer alteração em `backend/src/`.**

## Como eu quero que a IA trabalhe neste projeto

- Nunca recriar a estrutura do zero; evoluir a partir do que já existe.
- Antes de mexer em qualquer arquivo, avaliar se afeta leitura do ERP, leitura do banco, conciliação individual, conciliação por lote, ou as colunas do `Resultado.xlsx`.
- Sempre corrigir a **regra geral**, nunca criar caso especial por fornecedor/valor/descrição específica.
- Depois de qualquer mudança em `backend/src/`, rodar `cd backend && pytest` antes de considerar a tarefa concluída.
- Ao rodar `cd backend && python main.py`, sempre reportar o checklist completo: quantos lançamentos lidos do ERP/banco, quantos débitos/créditos, quantos conciliados por cada regra, quantos em Revisão Manual, Não encontrado, Somente banco (checklist completo em `CLAUDE.md`).
- Em caso de erro: explicar a causa provável, indicar o arquivo a alterar, corrigir a regra geral, rodar `main.py`, conferir, rodar `pytest`, e nunca remover regra que já funcionava.
- `backend/api/` e `frontend/` **nunca** podem conter regra de conciliação: são só transporte e apresentação. Toda correção de regra é feita em `backend/src/`.

## Onde encontrar mais detalhes
- `CLAUDE.md` — todas as regras de negócio, completas, com exemplos e motivos de Revisão Manual.
- `docs/REGRAS_DE_CONCILIACAO.md` — regras de conciliação detalhadas.
- `docs/HISTORICO_DECISOES.md` — histórico de todas as mudanças de regra, com data e motivo.
- `tests/README_TESTES.md` — o que cada teste cobre.
