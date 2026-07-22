# Conciliador Bancário - GestãoClick

## Objetivo do projeto

Este projeto automatiza a conciliação bancária entre:

- ERP GestãoClick (Excel exportado);
- extrato bancário de 1 banco (OFX ou Excel).

O foco atual é contas a pagar.

O projeto deve ser evoluído aos poucos. Nunca recriar do zero sem autorização.

## Estrutura do projeto

A estrutura correta é:

```text
Conciliador_Bancario/
├── dados/
│   ├── ERP/          -> Excel exportado do GestãoClick
│   └── Banco/         -> Extrato bancário (.ofx, .xlsx ou .xls)
├── resultado/
│   └── Resultado.xlsx -> gerado a cada execução (aba única — ver "Aba única")
├── logs/               -> um arquivo de log por dia
├── src/                -> código-fonte (ver módulos abaixo)
├── tests/              -> testes automáticos (pytest) que protegem as regras deste arquivo
├── docs/               -> documentação de estado, regras e histórico de decisões
├── main.py             -> ponto de entrada
├── requirements.txt
├── README.md
└── CLAUDE.md           -> este arquivo
```

Módulos de `src/`:

- `leitor_erp.py` — lê o Excel mais recente do ERP e define a Data ERP Usada por linha;
- `leitor_banco.py` — lê o extrato mais recente do banco (OFX ou Excel), filtra débitos e período;
- `conciliador.py` — toda a lógica de conciliação (fases 1 a 3, descritas abaixo);
- `exportador.py` — gera o `Resultado.xlsx` (aba única "Resultado");
- `utils.py` — funções auxiliares reutilizáveis (normalização de texto, detecção de colunas/cabeçalho, período do relatório etc.);
- `logger.py` — configuração do log;
- `ia_config.py` — configuração da camada de IA, lida exclusivamente de variável de ambiente (ver "Camada de IA" abaixo);
- `ia_revisor.py` — lógica pura (sem rede) da camada de IA: elegibilidade, seleção de candidatos, revalidação, resolução de conflitos e aplicação;
- `ia_cliente_groq.py` — único módulo que fala com a API da Groq (modelo `openai/gpt-oss-120b`), isolado para o resto do projeto continuar funcionando sem o pacote `groq` instalado quando a IA está desativada.

Esta estrutura não deve ser alterada sem autorização — o projeto deve apenas evoluir a partir daqui.

## Regras de proteção contra regressão

Sempre que alterar o código, o Claude deve preservar as regras que já funcionam.

Antes de modificar qualquer arquivo, verificar:

- se a alteração pode afetar a leitura do ERP (`leitor_erp.py`);
- se a alteração pode afetar a leitura do banco (`leitor_banco.py`);
- se a alteração pode afetar a conciliação individual (`conciliador.py`);
- se a alteração pode afetar a conciliação por lote NET EMP (`conciliador.py`);
- se a alteração pode afetar o `Resultado.xlsx` (`exportador.py`, colunas obrigatórias).

Depois de qualquer alteração em `src/`, rodar `pytest` (pasta `tests/`) antes de considerar a tarefa concluída — os testes existem exatamente para pegar regressão nessas regras.

Nunca corrigir um problema criando exceção específica por fornecedor.

Exemplo do que NÃO fazer:

- se fornecedor for "IB EXTINTORES", conciliar de tal forma;
- se descrição for "MOURO SOLUÇÕES", fazer regra especial;
- se valor for X, forçar conciliação.

Sempre corrigir a regra geral.

## Ordem obrigatória da conciliação

A ordem da conciliação deve ser sempre:

1. Ler ERP.
2. Definir Data ERP Usada por linha (prioridade: Data de compensação > Data de pagamento/baixa/confirmação — Vencimento NUNCA é usado). Uma linha sem nenhuma das duas fica com Data ERP Usada vazia e vai direto para Revisão Manual (motivo `MOTIVO_SEM_DATA_PAGAMENTO`), fora de qualquer fase abaixo.
3. Ler banco.
4. Filtrar banco para considerar somente débitos.
5. Filtrar banco pelo período do ERP.
6. Separar do lado do banco os lançamentos de lote claro NET EMP / NET EMPR (marcador + tipo específico) — esses nunca entram na conciliação individual.
7. Conciliar individualmente todos os lançamentos que sobraram (mesmo valor absoluto + mesma data). Um par único (1 ERP x 1 Banco) de Salário/Folha, Férias, Rescisão ou 13º só concilia direto quando há também nome/favorecido/descrição forte compatível — valor+data sozinhos nunca bastam para esses tipos (regra revisada em 2026-07-10, ver "Regras de lote NET EMP / NET EMPR"). Sem esse sinal, ficam retidos (não viram Revisão Manual) para a etapa de lote quando existe um lote bancário claro do mesmo tipo na mesma data exata.
8. Desempatar duplicidades de valor/data por descrição/nome.
9. Conciliar duplicidade idêntica individual (mesma descrição normalizada nos dois lados).
10. Conciliar duplicidade equivalente individual (ERP distingue por NF/documento, banco não).
11. Tolerância de data: só para pagamentos individuais (nunca lote NET EMP), até 1 dia, e só quando há nome/descrição forte compatível (regra revisada em 2026-07-10).
12. Conciliar lote NET EMP / NET EMPR por soma consolidada por data (Data ERP Usada EXATAMENTE igual à data do lote bancário, sem tolerância) e tipo.
13. Verificação final de possível par para "Não encontrado no banco" (regra de 2026-07-10, ver "Regra de recuperação de Não encontrado no banco") — só sobre o que sobrou de todas as fases acima.
14. Consolidar cada par ERP × Banco conciliado numa única linha (regra de 2026-07-10-b — ver "Regra 1: uma linha por par conciliado").
15. Gerar `Resultado.xlsx` — uma única aba (ver "Aba única").

## Regras de leitura do ERP

- A data usada na conciliação é a **Data ERP Usada**, escolhida linha a linha (nunca pela coluna inteira) nesta ordem de prioridade:
  1. **Data de compensação** — se a célula estiver preenchida naquela linha, ela é sempre usada.
  2. **Data de pagamento/baixa/liquidação** (ou "Data de confirmação", nome equivalente usado pelo GestãoClick) — usada linha a linha quando a Data de compensação está vazia.
- **Vencimento NUNCA é usado como Data ERP Usada** (regra revisada em 2026-07-10 — ver docs/HISTORICO_DECISOES.md; antes era o 3º fallback). Uma linha sem nenhuma data de pagamento/compensação/confirmação real fica com Data ERP Usada vazia — **não é descartada** e **nunca tenta casar com o banco**; vai direto para Revisão Manual com o motivo `ERP sem data de pagamento/compensação; vencimento não é usado para conciliação` (`MOTIVO_SEM_DATA_PAGAMENTO`), antes de qualquer fase de conciliação.
- As colunas de data originais (Data de compensação e Vencimento) são preservadas no resultado ("Data de Compensação Original", "Vencimento Original") para auditoria, mesmo quando não são a data usada — Vencimento Original nunca é usado para conciliar, só para consulta.
- A coluna de Valor aceita formato brasileiro (`1.234,56`, `R$ 1.234,56`, negativo entre parênteses).
- O cabeçalho da planilha é localizado automaticamente nas primeiras linhas (relatórios do GestãoClick trazem título/período antes da tabela).
- O período do relatório ("Período: DD/MM/AAAA à DD/MM/AAAA") é detectado automaticamente e usado para filtrar também o banco — ou pode ser fixado manualmente via `DATA_INICIAL_CONCILIACAO`/`DATA_FINAL_CONCILIACAO` em `utils.py`.

## Regras de leitura do banco

- Suporta OFX (com fallback de codificação: utf-8-sig, utf-8, cp1252, latin-1, iso-8859-1) e Excel.
- **Somente débitos/saídas são considerados.** Créditos, PIX recebido, TED recebida, depósito ou qualquer valor positivo são descartados **antes** da conciliação — nunca aparecem no Resultado.xlsx, nem como "Somente banco".
- Lançamentos com Data fora do período do ERP são ignorados e logados individualmente (data, valor, descrição, motivo).
- A comparação de valor entre ERP e banco é sempre feita pelo **valor absoluto** (um pagamento pode aparecer negativo no banco e positivo no ERP).

## Status permitidos

Apenas estes quatro valores podem aparecer na coluna "Status":

- `Conciliado`
- `Revisão Manual`
- `Não encontrado no banco`
- `Somente banco`

## Regras de tolerância de data

Revisadas em 2026-07-10 (ver `docs/HISTORICO_DECISOES.md`) — a tolerância não é mais única para todo o sistema:

- **Lote NET EMP/EMPR nunca usa tolerância de data.** Data Banco deve ser exatamente igual à Data ERP Usada. Se a data não bater, o lançamento não fecha automaticamente e vai para Revisão Manual com o motivo `Divergência de data para lote NET EMP`.
- **Pagamentos individuais (não-lote)** usam tolerância de **1 dia** (reduzida de 3) entre Data ERP Usada e Data Banco, dentro do mesmo valor absoluto — e só concilia automaticamente quando, além de candidato único dos dois lados, há **nome/favorecido/descrição forte compatível** (pelo menos 1 termo relevante em comum). Tipo Conciliação: `Valor, data (tolerância 1 dia) e nome`.
- Um candidato único dentro de 1 dia, mas **sem** nome/descrição forte, não concilia automaticamente — vai para Revisão Manual com motivo `Possível par com divergência de data (sem nome/descrição forte)`.
- **(2026-07-10-c)** Quando há **mais de um** candidato ERP/Banco do mesmo valor dentro da janela de tolerância (ex.: um grupo "Distribuição de Lucros" para várias pessoas, todas no mesmo valor e datas próximas — 1 dia de diferença entre ERP e Banco), o sistema tenta o mesmo pareamento por nome mutuamente único usado no grupo de data exata (ver "Regras de desempate por descrição/nome" abaixo), restrito aos pares que estão de fato dentro da tolerância de data — nunca escolhe ingenuamente "o primeiro candidato da lista". Quem não fechar com segurança fica em Revisão Manual com motivo `Empate de nome entre múltiplos candidatos` (quando há 2+ candidatos) ou `Possível par com divergência de data (sem nome/descrição forte)` (quando sobra só 1 candidato, sem nome compatível).

## Regras de desempate por descrição/nome

Quando há mais de um lançamento com o mesmo valor absoluto e a mesma data — ou o mesmo valor dentro da tolerância de 1 dia (2026-07-10-c) — de qualquer lado, a conciliação nunca resume em bloco — tenta resolver cada lançamento individualmente, nesta ordem:

1. Mesma descrição normalizada nos dois lados, mesma quantidade → duplicidade idêntica (ver abaixo).
2. Descrição normalizada bate mas quantidade diverge → Revisão Manual ("Quantidade divergente").
3. Termos relevantes (nomes próprios, números de documento) em comum entre ERP e banco, únicos e mútuos → concilia individualmente ("Valor, data e nome", ou "Valor, data (tolerância 1 dia) e nome" quando vem da fase de tolerância). Regra: 2+ termos compatíveis já é suficiente; com só 1 termo compatível, só vale se esse termo não aparecer em nenhum outro par candidato do mesmo grupo. **(2026-07-10-c)** Termo compatível agora inclui truncamento — ex.: "SILV" (como o banco às vezes abrevia) é compatível com "SILVA" (como está no ERP), desde que o prefixo tenha pelo menos 3 caracteres; e a lista de palavras genéricas ignoradas nessa comparação (`src/utils.py`) cresceu para incluir `CC`, `PARA`, `DISTRIBUICAO`, `LUCROS`, `TRANSFERENCIA`, `SALARIO`, `FOLHA`, `FERIAS`, `RESCISAO` — que antes "vazavam" como falso termo relevante e atrapalhavam (ou coincidentemente disfarçavam) o desempate.
4. Duplicidade equivalente (ver abaixo).
5. Sem nenhum sinal seguro → Revisão Manual (nunca adivinha).

## Regras de duplicidade idêntica

Quando **múltiplos** lançamentos (2 ou mais) têm a mesma descrição normalizada nos dois lados e a mesma quantidade — ex.: tarifas bancárias repetidas — cada lançamento concilia individualmente, um a um (nunca resumido em uma linha de grupo). Tipo Conciliação: `Duplicidade idêntica individual`.

## Regras de duplicidade equivalente

Quando o ERP distingue lançamentos por número de documento/NF (ex.: "Fornecedor X - NF 199" e "Fornecedor X - NF 200") mas o banco não reproduz esse número, a conciliação compara o "fornecedor base" (descrição sem números nem marcadores de documento como NF/DOC/PEDIDO). Só concilia quando há exatamente 1 cluster do banco compatível com exatamente 1 cluster do ERP (contenção mútua de termos) e a quantidade bate dos dois lados. Tipo Conciliação: `Duplicidade equivalente individual`.

## Regras de lote NET EMP / NET EMPR

Só é **lote claro** um lançamento bancário que tem, ao mesmo tempo:

1. um marcador NET EMP / NET EMPR / NET EMPRESA na descrição; **e**
2. um termo que indique claramente o tipo do pagamento: SALARIO/SALÁRIO/REMUNERACAO/REMUNERAÇÃO/FOLHA/PRO-LABORE (Salário/Folha), FERIAS/FÉRIAS (Férias), RESCISAO/RESCISÃO (Rescisão), ou 13/DECIMO/DÉCIMO (13º salário).

Exemplos que **são** lote claro: "PGTO SALARIO VIA NET EMP", "PGTO FERIAS VIA NET EMPR", "PGTO RESCISAO VIA NET EMP", "PGTO FOLHA VIA NET EMP", "PGTO 13 VIA NET EMP".

Exemplos que **não são** lote (seguem a conciliação individual normal, mesmo contendo "NET EMPRESA"): "PAG COBRANCA NET EMPRESA", "PAGTO ELETRON COBRANCA PAG COBRANCA NET EMPRESA" — não têm nenhum termo de tipo, então seriam pagamentos comuns tratados individualmente por valor e data. **Não existe "lote genérico"**: um marcador NET EMP/EMPR/EMPRESA sozinho, sem termo de tipo, nunca é suficiente para reservar como lote.

Lançamentos de lote claro do **banco** nunca devem ser conciliados individualmente por valor e data — são **reservados** para a etapa de lote **antes** de qualquer conciliação individual (passo 6 da ordem obrigatória), mesmo quando por coincidência um único lançamento do banco bate exatamente com um único lançamento do ERP.

O lado do **ERP** (Salário/Folha, Férias, Rescisão, 13º) **não** é bloqueado antes de tentar — ele participa normalmente da conciliação individual (valor + data, duplicidade idêntica/equivalente, desempate por nome) contra o banco que não é lote, para que um pagamento individual legítimo (ex.: um funcionário pago fora do lote, via PIX nomeado) seja conciliado corretamente antes do lote. Mas, diferente de um pagamento comum, **um par único (1 ERP x 1 Banco) desse tipo só concilia direto quando há também nome/favorecido/descrição forte compatível** — valor+data sozinhos nunca bastam (regra de 2026-07-10; antes disso, qualquer par único batia direto "Valor e data", inclusive remuneração). Sem esse sinal:

- se existir um lote bancário claro do mesmo tipo na mesma **data exata** (a nova tolerância de data para lote é zero — ver "Regras de tolerância de data"), o lançamento fica **retido** (não vira "Revisão Manual") para a etapa de lote tentar;
- senão, os dois lados (o ERP e o pagamento comum que coincidiu) vão para Revisão Manual com motivo `Remuneração/salário sem nome/descrição forte antes do lote`.

Essa proteção é **reativa**, não preventiva: nunca bloqueia o ERP antes de tentar, só decide o que fazer quando a tentativa não encontra evidência forte. Isso evita tanto "roubar" um pagamento individual genuíno do lote (bloqueio cego) quanto deixar uma coincidência de valor/data com um lançamento comum consumir, sem nenhum registro, um lançamento que de fato pertence ao lote.

Classificação do tipo de lote (mesma ordem de prioridade nos dois lados):

0. **(2026-07-10-d) Contém "FGTS" → nunca é lote, mesmo que também contenha um dos termos abaixo.** Depósito de FGTS vai sempre direto para a Caixa Econômica Federal, nunca é pago junto com o lote de folha da empresa (ex.: "FGTS - RESCISÃO FULANO", "FGTS - 13ª parcela" nunca são tratados como Rescisão/13º de lote).
1. Contém SALARIO/SALÁRIO/REMUNERACAO/REMUNERAÇÃO/FOLHA/PRO-LABORE → **Salário/Folha**
2. Contém FERIAS/FÉRIAS → **Férias**
3. Contém RESCISAO/RESCISÃO → **Rescisão**
4. Contém 13/DECIMO/DÉCIMO → **13º salário**

### Ordem de tentativa de fechamento do lote (sempre automática, nunca manual)

Para cada grupo (Data, Tipo de lote), o sistema tenta fechar automaticamente nesta ordem, sempre em **centavos inteiros** (nunca ponto flutuante) e **nunca adivinhando**:

**Etapa A — total direto.** Soma-se **todos** os lançamentos bancários NET EMP ainda não conciliados dessa data/tipo e **todos** os candidatos do ERP ainda não conciliados do mesmo tipo com a mesma Data ERP Usada **exata** (sem tolerância — regra de 2026-07-10). Se as duas somas baterem exatamente, concilia todo o grupo. Tipo Conciliação: `Lote NET EMP consolidado por data`.

**Etapa B — combinação exata única.** Se o total do ERP for **maior** que o total do banco, procura um subconjunto dos candidatos do ERP cuja soma feche exatamente o total do banco (busca meet-in-the-middle, segura até 40 candidatos). Só concilia se existir **exatamente uma** combinação possível — os candidatos fora dela viram "Não encontrado no banco" (a soma exata prova que não pertencem a este lote). Duas ou mais combinações possíveis → nunca adivinha, Revisão Manual. Tipo Conciliação: `Lote NET EMP por combinação exata única`.

**Etapa C — nome/descrição.** Só tentada quando a descrição do banco do grupo traz um identificador individual (nome, CPF, documento) além do vocabulário genérico do lote — nunca para bancos genéricos como "PGTO SALARIO VIA NET EMP" sozinho. Tenta parear cada lançamento do banco com um candidato do ERP por termos mutuamente únicos (mesmo algoritmo do desempate por nome da conciliação individual); só aceita se resolver **todos** os lançamentos do banco do grupo. Tipo Conciliação: `Lote NET EMP por nome/descrição individual`.

Se **nenhuma etapa fechar**, todo o grupo fica em Revisão Manual, com um destes Motivo Revisão (regra 11):

- `Total ERP candidato menor que total banco NET EMP` — o total do ERP não alcança o do banco (nenhuma etapa consegue fechar isso).
- `Múltiplas combinações possíveis para o lote NET EMP` — Etapa B encontrou 2 ou mais combinações.
- `Nenhuma combinação exata encontrada para o lote NET EMP` — o banco trouxe identificador individual, mas nem a combinação nem o nome resolveram.
- `Banco genérico sem nome e sem combinação única possível` — banco sem identificador e nenhuma combinação exata.
- `Divergência de data para lote NET EMP` (2026-07-10) — existem candidatos do ERP desse tipo nesta execução, mas nenhum com a mesma Data ERP Usada exata do lote bancário (lote não usa tolerância de data).

O `ID Lote` (ex.: `FERIAS-2026-05-12-001`, `SALARIO-2026-05-06-001`) é o mesmo para todos os lançamentos que fecharem o mesmo grupo (Etapa A, B ou C). Nunca resume o lote em uma linha única — cada lançamento (ERP e banco) continua aparecendo em sua própria linha no Resultado.xlsx.

### Não existe conciliação manual do lote

A conciliação do lote NET EMP é **sempre automática**, baseada só em evidência matemática (total direto, combinação exata única) ou de nome/descrição do próprio banco. Não existe nenhuma aba ou coluna para o usuário marcar manualmente quais lançamentos pertencem ao lote — quando nenhuma etapa fecha com segurança, o lote fica em Revisão Manual, com o motivo específico explicando qual etapa falhou e por quê.

## Diferença entre PIX individual e lote NET EMP

- PIX, TED e DOC **individuais** (com nome específico do favorecido) nunca são candidatos à regra de lote — mesmo que haja vários no mesmo dia. São sempre conciliados pela conciliação individual (valor + data, ou desempate por nome quando ambíguos).
- Só entram na regra de lote lançamentos cuja descrição contenha termos NET EMP/NET EMPR/NET EMPRESA (ou as variações "PGTO ... VIA NET EMP/EMPR" listadas acima) — e mesmo assim, a exclusão de PIX/TED/DOC/"transferência individual" tem prioridade sobre essa inclusão.

## Regra de vencimento nunca usado

Ver "Regras de leitura do ERP" acima. Resumo: Vencimento nunca vira Data ERP Usada; uma linha só-com-vencimento fica com Data ERP Usada vazia, é preservada (nunca descartada silenciosamente) e vai direto para Revisão Manual com motivo `ERP sem data de pagamento/compensação; vencimento não é usado para conciliação` — nunca tenta casar com o banco.

## Regra de recuperação de "Não encontrado no banco"

Regra de 2026-07-10 (ver `docs/HISTORICO_DECISOES.md`), revisada em 2026-07-10-d. Antes de finalizar um lançamento do ERP como "Não encontrado no banco", o sistema verifica — **só depois de todas as fases principais** (individual, tolerância, lote), para nunca interferir nelas — se existe um possível par no banco (usado ou não) por valor absoluto + data:

1. **Candidato único por valor+data, ainda pendente, mutuamente único (nenhum outro ERP desta verificação também disputa o mesmo banco)** → concilia. **(2026-07-10-d) Nome/descrição não é mais exigido aqui** — valor e data já bastam quando não há nenhuma ambiguidade. Status `Conciliado`; Tipo Conciliação `Valor e data` (ou `Valor, data e nome` quando o nome também bate, só para enriquecer o rótulo); Observações `Conciliado por valor e data únicos (verificação de possível "Não encontrado no banco")` (ou a observação de nome, quando aplicável).
2. **Existe mais de um candidato do banco com o mesmo valor+data, ou o único candidato também é disputado por outro ERP desta lista** → Revisão Manual, motivo `Múltiplos bancos possíveis para ERP marcado como Não encontrado` — nunca escolhe um sozinho.
3. **Nenhum candidato na mesma data, mas existe exatamente 1 candidato com mesmo valor e nome forte compatível em outra data** → Revisão Manual, motivo `Possível par encontrado com divergência de data`.
4. **Candidato único por valor+data, mas o banco já foi consumido por outro lançamento** → Revisão Manual, motivo `Possível par bancário já consumido por outro lançamento` — **nunca desfaz** a conciliação anterior para "roubar" o banco; só registra o conflito.
5. **Nenhum candidato por nenhuma via** → mantém "Não encontrado no banco" (comportamento anterior), mas a coluna "Motivo Não Conciliado" da própria linha explica que nenhum candidato foi achado (2026-07-10-b: não existe mais aba separada — ver "Aba única").

Nunca força conciliação quando há risco real (múltiplos candidatos por valor+data, de qualquer lado, ou banco já usado) — só concilia quando o par é matematicamente inequívoco (valor+data únicos e mutuamente únicos) ou tem nome mutuamente único. Essa verificação é centrada no ERP: não reclassifica o lado do banco, exceto quando o par é efetivamente conciliado.

**(2026-07-10-d) "FGTS" nunca é candidato a lote NET EMP.** Além da verificação acima, a classificação de tipo de lote (`_classificar_tipo_lote`) passou a excluir qualquer texto contendo "FGTS" — mesmo quando também contém "RESCISÃO", "13" ou outro marcador de tipo (ex.: "FGTS - RESCISÃO FULANO", "FGTS - 13ª parcela"). Motivo: depósitos de FGTS vão sempre direto para a Caixa Econômica Federal, nunca são pagos junto com o lote de folha da empresa — sem essa exclusão, a trava de "remuneração sem nome antes do lote" (ver seção de lote) bloqueava indevidamente a conciliação direta por valor e data desses lançamentos, mesmo sem nenhum lote NET EMP por perto.

## Regras de revisão manual

Nunca adivinhar. Mantém Revisão Manual quando:

- há mais de um candidato com o mesmo valor e data e a descrição/nome não é suficiente para desempatar com segurança;
- a quantidade diverge entre ERP e banco para a mesma descrição normalizada;
- há indício de duplicidade equivalente (fornecedor base bate) mas não é possível confirmar com segurança (quantidade ou concorrência);
- um par único (ou candidato de tolerância) de Salário/Folha, Férias, Rescisão ou 13º bate em valor+data mas não tem nome/descrição forte compatível, e não há lote bancário claro do mesmo tipo na mesma data exata para reter o lançamento (`Remuneração/salário sem nome/descrição forte antes do lote`, 2026-07-10);
- um pagamento individual só bate por proximidade de data (tolerância de 1 dia) sem nome/descrição forte (`Possível par com divergência de data (sem nome/descrição forte)`, 2026-07-10);
- o lote NET EMP não fecha em nenhuma das 3 etapas (total direto, combinação exata única, nome/descrição), inclusive quando é por divergência de data — ver seção de lote para os 5 motivos possíveis;
- o ERP não tem nenhuma data de pagamento/compensação real, só vencimento (`ERP sem data de pagamento/compensação; vencimento não é usado para conciliação`, 2026-07-10);
- a verificação final de "Não encontrado no banco" achou algum indício, mas não segurança suficiente (ver "Regra de recuperação de Não encontrado no banco");
- não há nenhuma evidência segura de correspondência.

O "Motivo Revisão" sempre identifica qual dessas situações ocorreu (ver `docs/REGRAS_DE_CONCILIACAO.md` para o texto de cada motivo).

## Colunas obrigatórias do Resultado.xlsx

A aba "Resultado" deve manter, no mínimo, estas colunas:

- Data ERP Usada
- Tipo Data ERP
- Data de Compensação Original
- Vencimento Original
- Data Banco
- Valor ERP
- Valor Banco
- Favorecido
- Descrição ERP
- Descrição Banco
- Status
- Tipo Conciliação
- Observações
- Motivo Revisão
- Motivo Não Conciliado (nova em 2026-07-10-b — ver "Regra 1: uma linha por par conciliado")
- Diferença de Dias
- ID Lote
- Possível Data Banco (nova em 2026-07-10-b)
- Possível Valor Banco (nova em 2026-07-10-b)
- Possível Descrição Banco (nova em 2026-07-10-b)
- Status do Possível Banco (nova em 2026-07-10-b)
- Origem (`ERP`, `Banco`, ou `ERP+Banco` quando a linha representa um par 1‑para‑1 já mesclado — ver regra abaixo)

Quando `IA_MODO` (ver "Camada de IA" abaixo) for `SOMBRA` ou `AUTOMATICO`, a aba ganha mais 5 colunas ao final: Decisão IA, Confiança IA, Motivo IA, Validação IA, Modelo IA. Em `IA_MODO=DESATIVADA` (default) essas colunas **não existem** — a aba fica idêntica ao que sempre foi.

## Regra 1: uma linha por par conciliado (2026-07-10-b)

Revisada em 2026-07-10 (ver `docs/HISTORICO_DECISOES.md`). Cada par ERP × Banco efetivamente conciliado (correspondência 1‑para‑1 inequívoca) aparece em **uma única linha** do Resultado.xlsx — nunca uma linha "do lado ERP" e outra espelhada "do lado Banco" para o mesmo par. Essa linha traz os dados dos dois lados e `Origem = "ERP+Banco"`.

- Um ID ERP conciliado nunca aparece em mais de uma linha "Conciliado"; o mesmo vale para um ID Banco.
- Duplicidades **reais** (ex.: 2 tarifas de R$ 9,80 no mesmo dia, dos dois lados) continuam em linhas separadas — cada uma é um par diferente (índices diferentes), não a mesma linha repetida.
- Grupos de **lote NET EMP** com mais de um lançamento de qualquer lado (a maioria dos casos) continuam com uma linha por lançamento — nunca resumidos numa única linha — porque não são uma correspondência 1‑para‑1; só quando um lote fecha com exatamente 1 ERP e 1 Banco é que essa mesma regra de mesclagem se aplica.
- Verificação defensiva: se, por algum bug, o mesmo índice ERP ou o mesmo índice Banco fosse associado a mais de um par, o sistema nunca escolhe um sozinho — rebaixa essas linhas para Revisão Manual com o motivo `Mesmo lançamento ERP/Banco foi associado a mais de um par possível`. Na prática isso nunca deveria disparar, já que cada fase da conciliação só consome de pools de pendentes disjuntos.

## Aba única (2026-07-10-b)

O `Resultado.xlsx` tem **uma única aba**, chamada "Resultado" — não existem mais abas separadas de diagnóstico (Diagnóstico Revisão Manual, Diagnóstico Lotes NET EMP, Diagnóstico Não Encontrados). Toda informação de diagnóstico que antes vivia nessas abas agora é coluna da própria linha:

- o motivo de um "Não encontrado no banco" ou "Somente banco" fica em **Motivo Não Conciliado**;
- o possível candidato bancário encontrado (quando existe) para um ERP em Revisão Manual ou Não encontrado fica em **Possível Data/Valor/Descrição Banco** e **Status do Possível Banco**;
- o detalhe financeiro completo de cada grupo de lote NET EMP (totais, diferença, resultado de cada etapa de tentativa) continua disponível no arquivo de log do dia (`logs/`) — não é mais exportado como aba, mas nunca é descartado.

## Camada de IA (2ª etapa decisiva de conciliação)

Ver `docs/HISTORICO_DECISOES.md` para o histórico completo da decisão. Resumo das regras:

- A IA só analisa o que sobrar com `Status == "Revisão Manual"` **depois de todas as fases determinísticas acima** — nunca substitui, desfaz ou reabre uma conciliação já feita pelo Python.
- Três modos, controlados **só por variável de ambiente** (`.env`, ver `.env.example` e `src/ia_config.py` — nunca uma constante fixa em `src/utils.py`):
  - `IA_MODO=DESATIVADA` (default): a etapa nem roda; `COLUNAS_RESULTADO` fica exatamente como sempre foi, sem nenhuma coluna nova.
  - `IA_MODO=SOMBRA`: roda a mesma análise/validação de `AUTOMATICO`, mas nunca altera `Status` nem consome nenhum índice — só preenche as 6 colunas de auditoria da IA com o que teria acontecido.
  - `IA_MODO=AUTOMATICO`: uma decisão `CONCILIAR` aprovada em todas as revalidações do Python concilia de verdade, sem revisão humana.
- Provedor: Groq API (SDK `groq`), modelo padrão e recomendado `openai/gpt-oss-120b` (Structured Outputs com `strict=true`). `GROQ_API_KEY`/`GROQ_MODEL` são obrigatórios sempre que `IA_MODO` for `SOMBRA`/`AUTOMATICO`; se qualquer um faltar, a camada é desativada automaticamente nesta execução (com aviso no log) — nunca derruba `python main.py`. A chave de API nunca é escrita em nenhuma linha de log.
- Elegibilidade (todos simultâneos): `Status == "Revisão Manual"`, `Origem == "ERP"`, `Data ERP Usada` preenchida, `Motivo Revisão` numa lista branca fixa (nunca lista negra) e o lançamento não pertencer a nenhum tipo de lote NET EMP (Salário/Folha, Férias, Rescisão, 13º) — verificado via `_classificar_tipo_lote`.
- Lista branca de motivos elegíveis (`MOTIVOS_ELEGIVEIS_IA` em `src/ia_revisor.py`): `Duplicidade de valor e data sem descrição suficiente`, `Descrição/nome incompatível`, `Possível par com divergência de data (sem nome/descrição forte)`, `Empate de nome entre múltiplos candidatos`, `Possível par encontrado com divergência de data`, `Múltiplos bancos possíveis para ERP marcado como Não encontrado`, e (por completude, hoje nunca produzido) o motivo de "não encontrado sem evidência".
- **Nunca elegíveis**, mesmo em Revisão Manual: `ERP sem data de pagamento/compensação...`, `Remuneração/salário sem nome/descrição forte antes do lote`, qualquer motivo de lote NET EMP, `Mesmo lançamento ERP/Banco foi associado a mais de um par possível`, `Quantidade divergente`, `Possível duplicidade equivalente não resolvida`, `Possível par bancário já consumido por outro lançamento` — banco já consumido nunca é candidato.
- Candidatos bancários: no máximo `IA_MAXIMO_CANDIDATOS` (default 5), pré-filtrados por valor absoluto exato e diferença de data até `IA_JANELA_BUSCA_DIAS` (default 5 dias) — nunca vindos de lote reservado nem já consumidos por outro par.
- A IA responde só `{decisao: CONCILIAR|MANTER_REVISAO|NENHUM_CANDIDATO, candidato: um dos IDs oferecidos ou null, confianca: 0-1, motivo}` via Structured Outputs (JSON Schema, `strict=true`) forçado (nunca texto livre). O `enum` de `candidato` no schema é sempre fixo (`C1`..`C5`+null); quem garante que só um ID de fato oferecido naquela chamada é aceito é a revalidação do Python (`_validar_estrutura_resposta`), não o schema em si.
- Antes de qualquer `CONCILIAR` valer alguma coisa, o Python revalida: candidato pertence à lista oferecida; valor exato; banco ainda disponível; banco não é de lote; ERP não é de lote; confiança ≥ limite do **modo ativo** (`IA_CONFIANCA_MINIMA_SOMBRA`, default 0,70, ou `IA_CONFIANCA_MINIMA_AUTOMATICO`, default 0,95 — bem mais estrita); e, só em `AUTOMATICO`, diferença de data ≤ `IA_JANELA_AUTOMATICA_DIAS` (default 1 dia) — um candidato de 2 a 5 dias nunca concilia sozinho automaticamente na primeira versão, mesmo com alta confiança.
- Se **2 ou mais** lançamentos do ERP escolherem o mesmo candidato bancário, **nenhuma** das decisões conflitantes é aplicada — todas continuam em Revisão Manual (nunca escolhe sozinho, mesma filosofia da verificação defensiva de par conflitante).
- Uma decisão `CONCILIAR` aplicada em `AUTOMATICO` usa `Tipo Conciliação = "IA validada pelo Python"` e recebe `_par_id=(índice ERP, índice Banco)`, exatamente como qualquer fase determinística — a consolidação de par único (`_consolidar_pares_conciliados`) funde a linha sem precisar de nenhuma alteração própria.
- Nenhum lançamento ERP ou Banco é usado mais de uma vez; nunca são criados pares duplicados ou espelhados.

## Testes automáticos

A pasta `tests/` (pytest) protege as regras deste arquivo com testes que fabricam dados sintéticos e chamam `conciliar()`/`selecionar_data_prioritaria()`/`ler_banco()` diretamente (sem depender dos arquivos reais em `dados/`). Ver `tests/README_TESTES.md` para detalhes de como rodar e o que cada teste cobre. Rodar `pytest` sempre que alterar `src/` é parte obrigatória do fluxo de mudança.

## Casos de teste obrigatórios

Depois de qualquer alteração, verificar se estes tipos de caso continuam funcionando (cobertos por `tests/`):

### 1. Data de compensação

Se o ERP tiver Data de compensação preenchida, nunca usar Vencimento. Se não tiver, usar Data de pagamento/baixa/confirmação. **Vencimento nunca é usado** (2026-07-10) — uma linha só-com-vencimento fica com Data ERP Usada vazia e vai para Revisão Manual com motivo específico, sem tentar casar com o banco.

### 2. Débitos do banco

O banco deve considerar somente saídas/débitos. Créditos, PIX recebido, TED recebida, depósito ou valores positivos não devem aparecer como Somente banco.

### 3. Duplicidade com descrição diferente

Se houver dois lançamentos com mesmo valor e mesma data, mas descrições diferentes que permitam identificação, conciliar por descrição/nome.

### 4. Tarifas repetidas

Se houver tarifas repetidas com mesma data, mesmo valor e mesma descrição no ERP e no banco, conciliar individualmente uma a uma.

### 5. Lote NET EMP

Se a soma dos lançamentos ERP restantes de uma data bater exatamente com a soma dos lançamentos bancários NET EMP / NET EMPR da mesma data, conciliar por lote (nunca por valor e data isolado, mesmo coincidindo).

### 6. PIX individual

PIX individual com nome específico não deve entrar na regra de lote. Deve ser conciliado individualmente por valor, data e descrição/nome.

### 7. Combinação exata única do lote NET EMP

Quando o total de candidatos do ERP de um lote é maior que o total do banco, o sistema busca automaticamente um subconjunto dos candidatos cuja soma feche exatamente o total do banco. Só concilia quando existe exatamente 1 combinação possível; 2 ou mais → Revisão Manual (nunca adivinha). Não existe nenhuma marcação manual.

### 8. Recuperação de "Não encontrado no banco" (2026-07-10, revisado em 2026-07-10-d)

Um ERP que ficaria "Não encontrado no banco" deve ser verificado contra o banco inteiro (usado ou não) por valor+data antes de finalizar: candidato único por valor+data, pendente e mutuamente único → concilia por "Valor e data" (nome não é mais exigido — só enriquece para "Valor, data e nome" quando também bate); qualquer outro indício (múltiplos candidatos por valor+data, banco já consumido, só divergência de data em outra data) → Revisão Manual com motivo específico, nunca "Não encontrado" sem explicação. Nunca troca uma conciliação já feita. "FGTS" nunca é tratado como candidato a lote NET EMP, mesmo contendo "RESCISÃO"/"13" no texto.

## Checklist após executar python main.py

Depois de rodar `python main.py`, o Claude deve informar:

- se o Resultado.xlsx foi gerado;
- quantos lançamentos foram lidos do ERP;
- quantos lançamentos foram lidos do banco;
- quantos débitos foram considerados;
- quantos créditos foram ignorados;
- quantos lançamentos usaram Data de compensação;
- quantos ficaram sem Data ERP Usada por terem só vencimento (Vencimento nunca é usado como fallback — 2026-07-10);
- quantos foram conciliados por valor e data;
- quantos foram conciliados por descrição/nome;
- quantos foram conciliados por duplicidade individual;
- quantos foram conciliados por lote NET EMP;
- quantos "Não encontrado no banco" foram recuperados como Conciliado ou Revisão Manual pela verificação final (2026-07-10);
- quantos ficaram em Revisão Manual;
- quantos ficaram como Não encontrado no banco;
- quantos ficaram como Somente banco;
- se `IA_MODO` estava `SOMBRA`/`AUTOMATICO`: quantos lançamentos foram avaliados pela IA e, em `AUTOMATICO`, quantos foram conciliados automaticamente (`Tipo Conciliação = "IA validada pelo Python"`).

## Quando houver erro

Se alguma regra falhar, o Claude deve:

1. Explicar a causa provável.
2. Indicar qual arquivo será alterado.
3. Corrigir a regra geral.
4. Rodar `python main.py`.
5. Conferir se o erro foi resolvido.
6. Rodar `pytest` para confirmar que nada mais quebrou.
7. Não remover regras anteriores que já estavam funcionando.
