# Estado atual do projeto — Conciliador Bancário GestãoClick

> Snapshot do projeto no momento em que foi escrito. Reflete o comportamento real do código em `src/` nesta data. Se o código evoluir, este arquivo deve ser atualizado junto — ele não se atualiza sozinho.

## Objetivo do projeto

Automatizar a conciliação bancária entre o Excel exportado do ERP GestãoClick (contas a pagar) e o extrato bancário de 1 banco (OFX ou Excel), rodando por terminal/VS Code, sem interface gráfica.

## Estrutura de pastas

```
Conciliador_Bancario/
├── dados/
│   ├── ERP/          Excel exportado do GestãoClick
│   └── Banco/         Extrato bancário (.ofx, .xlsx ou .xls)
├── resultado/
│   └── Resultado.xlsx  gerado a cada execução (aba única, 2026-07-10-b)
├── logs/                um arquivo de log por dia
├── src/                 código-fonte
├── tests/                testes automáticos (pytest)
├── docs/                 este arquivo e os demais documentos de apoio
├── main.py
├── requirements.txt
├── README.md
└── CLAUDE.md
```

## Comando principal para executar

```
python main.py
```

Lê o Excel mais recente de `dados/ERP/`, o extrato mais recente de `dados/Banco/`, concilia e grava `resultado/Resultado.xlsx`.

Para rodar os testes automáticos:

```
pytest
```

## Regras atuais da leitura do ERP

- Cabeçalho da tabela é localizado automaticamente (relatórios do GestãoClick trazem título/período antes da tabela real).
- Colunas de Data, Valor e Favorecido são detectadas por nome (com sinônimos), não por posição fixa.
- Valor aceita formato brasileiro (`1.234,56`, `R$`, negativo entre parênteses).
- Cada linha recebe uma **Data ERP Usada** e um **Tipo Data ERP** (rótulo de qual coluna original foi usada).
- Colunas de auditoria "Data de Compensação Original" e "Vencimento Original" são preservadas mesmo quando não são a data escolhida.
- O período do relatório ("Período: DD/MM/AAAA à DD/MM/AAAA") é detectado automaticamente e usado depois para filtrar o banco.

## Regra da Data de compensação

Se a célula "Data de compensação" estiver preenchida naquela linha do ERP, ela **sempre** é usada como Data ERP Usada — mesmo que Vencimento também esteja preenchido na mesma linha. A decisão é tomada linha a linha, nunca pela coluna inteira.

## Regra do Vencimento — NUNCA usado (revisada em 2026-07-10)

Vencimento **nunca** é usado como Data ERP Usada (antes era o último fallback da cadeia — removido). Uma linha sem Data de compensação **nem** Data de pagamento/baixa/confirmação preenchida fica com Data ERP Usada vazia (`NaT`): `src/leitor_erp.py` preserva a linha (não descarta mais por falta de data, só por falta de Valor), e `src/conciliador.py` a separa **antes** de qualquer fase de conciliação, marcando-a Revisão Manual com o motivo `ERP sem data de pagamento/compensação; vencimento não é usado para conciliação` — nunca tenta casar com o banco usando o vencimento. A coluna "Vencimento Original" continua sendo lida e exibida só para auditoria.

## Regras da leitura do banco

- Suporta OFX (com fallback de codificação utf-8-sig → utf-8 → cp1252 → latin-1 → iso-8859-1, e remoção de linha em branco antes do cabeçalho OFX quando presente) e Excel.
- Extrai Data, Valor e Favorecido (payee ou memo, no caso de OFX).

## Regra de considerar somente débitos

Depois de ler o extrato, o código filtra `Valor < 0` — só débitos/saídas seguem para a conciliação. Esse filtro acontece **antes** de qualquer outra etapa.

## Regra de ignorar créditos

Créditos (PIX recebido, TED recebida, depósito, qualquer valor positivo) são descartados no mesmo filtro acima. Como são descartados antes da conciliação, **nunca** podem aparecer como "Somente banco" — não chegam a ser avaliados.

## Regra de filtro por período

Lançamentos do banco com Data fora do período do relatório do ERP são descartados e logados individualmente (data, valor, descrição, motivo "Fora do período da conciliação"). O período pode ser detectado automaticamente ou fixado manualmente via `DATA_INICIAL_CONCILIACAO`/`DATA_FINAL_CONCILIACAO` em `src/utils.py`.

## Status permitidos

Somente estes quatro valores existem na coluna "Status":

- `Conciliado`
- `Revisão Manual`
- `Não encontrado no banco`
- `Somente banco`

## Ordem completa da conciliação

1. Ler ERP.
2. Definir Data ERP Usada por linha (Vencimento nunca é usado — 2026-07-10). Linha sem data de pagamento/compensação real vira Revisão Manual direto, fora de qualquer fase abaixo.
3. Ler banco.
4. Filtrar banco: somente débitos.
5. Filtrar banco: somente dentro do período do ERP.
6. Separar do lado do banco os lançamentos NET EMP/EMPR (reservados para lote, nunca entram na conciliação individual).
7. Conciliar individualmente (valor absoluto + data exata) tudo que sobrou — inclusive o ERP de Salário/Folha, Férias, Rescisão e 13º, mas um par único desse tipo só concilia direto com nome/descrição forte compatível (2026-07-10). Sem esse sinal, fica retido para o lote se houver um lote bancário claro do mesmo tipo na mesma data exata (ver "Regras de lote NET EMP" abaixo).
8. Desempatar duplicidades de valor/data por descrição/nome.
9. Conciliar duplicidade idêntica individual.
10. Conciliar duplicidade equivalente individual.
11. (Fase de tolerância de datas — só pagamentos individuais, 1 dia, com nome/descrição forte obrigatória; nunca lote NET EMP — 2026-07-10; roda entre os passos 7/10 e 12 para o que sobrou sem par exato, ver `conciliador.py`.)
12. Conciliar lote NET EMP/EMPR por soma consolidada (por data EXATA e tipo — sem tolerância de data desde 2026-07-10).
13. Verificação final de possível par para o que sobrou antes de virar "Não encontrado no banco" (2026-07-10, ver "Regra de recuperação de Não encontrado no banco" abaixo) — só sobre o que sobrou de todas as fases acima.
14. Finalizar o que ainda não teve par nenhum como "Não encontrado no banco" / "Somente banco".
15. Gerar `Resultado.xlsx`.
16. Consolidar cada par ERP × Banco conciliado numa única linha (2026-07-10-b) e gerar a aba única "Resultado".

## Regras de desempate por descrição/nome

Dentro de um grupo com o mesmo valor absoluto e mesma data (mais de 1 lançamento de algum lado), o sistema extrai "termos relevantes" (nomes próprios, números de documento) de cada descrição, removendo palavras genéricas de banco/ERP (PAGTO, PIX, TED, REEMBOLSO, AUXILIO etc.). Regra de confirmação:

- 2 ou mais termos em comum entre um ERP e um Banco → correspondência válida.
- Só 1 termo em comum → só vale se esse termo não aparecer em nenhum outro par candidato do mesmo grupo (evita termo ambíguo decidir sozinho).
- Só confirma o par se ele for a única correspondência válida dos dois lados (nunca adivinha).

## Regras de duplicidade idêntica

Quando há 2 ou mais lançamentos com a mesma descrição normalizada nos dois lados **e** a mesma quantidade (ex.: tarifas bancárias repetidas), cada um concilia individualmente, pareado por ordem — nunca resumido em uma linha de grupo. Se a quantidade divergir, todos ficam em Revisão Manual ("Quantidade divergente").

## Regras de duplicidade equivalente

Quando o ERP distingue por número de documento/NF (ex.: "Fornecedor X - NF 199"/"NF 200") mas o banco não reproduz esse número, o sistema compara o "fornecedor base" (descrição sem dígitos nem marcadores de documento como NF/DOC/PEDIDO/REF). Só concilia quando há exatamente 1 cluster do banco compatível com exatamente 1 cluster do ERP e a quantidade bate dos dois lados.

## Regras de lote NET EMP / NET EMPR

- Candidatos do banco ("lote claro"): a descrição precisa ter **ao mesmo tempo** um marcador (NET EMP, NET EMPR, NET EMPRESA) **e** um termo de tipo específico (SALARIO/REMUNERACAO/FOLHA/PRO-LABORE, FERIAS, RESCISAO ou 13/DECIMO) — **exceto** se contiver PIX, TED, DOC ou "transferência individual" (essas nunca entram em lote). Um marcador NET EMP/EMPRESA sozinho, sem termo de tipo (ex.: "PAG COBRANCA NET EMPRESA", "PAGTO ELETRON COBRANCA"), **não** é tratado como lote — segue a conciliação individual normal.
- O **banco** é reservado **antes** de qualquer conciliação individual (nunca compete por valor+data com lançamentos comuns).
- O **ERP**: participa normalmente da fase 1 (conciliação individual) contra o banco que não é lote — mas (2026-07-10) um **par único** desse tipo só concilia direto quando há também nome/favorecido/descrição forte compatível (`_nome_compativel`, pelo menos 1 termo relevante em comum); valor+data sozinhos nunca "roubam" um candidato do lote por coincidência. Sem esse sinal: se existir um lote bancário claro do mesmo tipo na **mesma data exata** (lote não usa tolerância — ver abaixo), o lançamento fica retido para a etapa de lote; senão, os dois lados (ERP e o pagamento comum que coincidiu) vão para Revisão Manual com motivo `Remuneração/salário sem nome/descrição forte antes do lote`. Isso deixa pagamentos individuais legítimos (ex.: funcionário pago fora do lote, via PIX nomeado) conciliarem corretamente antes do lote, e reduz o pool de candidatos do lote só pelos que realmente saíram por outra via — nunca por bloqueio cego.
- Classificados por tipo: Salário/Folha, Férias, Rescisão ou 13º salário (não existe tipo "genérico").
- **Lote NET EMP não usa tolerância de data nenhuma** (2026-07-10, antes ±3 dias): a Data ERP Usada do candidato precisa ser exatamente igual à data do lote bancário. Quando não há candidato do tipo certo na data exata (mas existem em outra data), o grupo/lançamento fica em Revisão Manual com motivo `Divergência de data para lote NET EMP`.
- Fechamento **sempre automático**, em 3 etapas (nunca depende de marcação manual — removida em 2026-07-09):
  1. **Total direto** — soma todos os candidatos de cada lado ainda não conciliados com a mesma data exata do lote; se as somas baterem exatamente (em centavos inteiros), concilia tudo. Tipo Conciliação: `Lote NET EMP consolidado por data`.
  2. **Combinação exata única** — se o total do ERP for maior que o do banco, busca (meet-in-the-middle, segura até 40 candidatos) um subconjunto dos candidatos cuja soma feche exatamente o total do banco. Só concilia se existir exatamente 1 combinação; os candidatos fora dela viram "Não encontrado no banco". 2+ combinações → Revisão Manual (nunca adivinha). Tipo Conciliação: `Lote NET EMP por combinação exata única`.
  3. **Nome/descrição** — só tentada quando a descrição do banco do grupo tem um identificador individual (nome, CPF, documento) além do vocabulário genérico do lote; reaproveita o mesmo algoritmo de desempate por nome da conciliação individual, só aceitando se resolver todos os lançamentos do banco do grupo. Tipo Conciliação: `Lote NET EMP por nome/descrição individual`.
- Se nenhuma das 3 etapas fechar, Revisão Manual com um destes 5 motivos: `Total ERP candidato menor que total banco NET EMP`, `Múltiplas combinações possíveis para o lote NET EMP`, `Nenhuma combinação exata encontrada para o lote NET EMP`, `Banco genérico sem nome e sem combinação única possível`, `Divergência de data para lote NET EMP` (2026-07-10).
- `ID Lote` é compartilhado por todos os lançamentos do mesmo grupo (ex.: `FERIAS-2026-05-12-001`), qualquer que seja a etapa que fechou.

## Diferença entre PIX individual e lote NET EMP

PIX/TED/DOC com nome específico do favorecido **nunca** são candidatos a lote, mesmo que se repitam várias vezes no mesmo dia — são sempre resolvidos pela conciliação individual (par único ou desempate por nome). Só entra em lote quem tem termo NET EMP/EMPR na descrição **e** não tem PIX/TED/DOC/"transferência individual" (essa exclusão tem prioridade).

## Regra de recuperação de "Não encontrado no banco" (2026-07-10)

Antes de finalizar um ERP como "Não encontrado no banco" (`_verificar_possiveis_pares_nao_encontrados` em `src/conciliador.py`, chamada só depois de todas as fases principais), verifica se existe possível par no banco (usado ou não) por valor absoluto + data + nome/descrição:

- candidato único, mesma data, nome forte, pendente, mutuamente único → concilia (`Valor, data e nome`, Observações "Conciliado após verificação de possível 'Não encontrado no banco'");
- candidato(s) na mesma data sem nome forte, ou 2+ candidatos → Revisão Manual (`Existe lançamento bancário com mesmo valor e mesma data, mas sem evidência suficiente para conciliação automática` ou `Múltiplos bancos possíveis para ERP marcado como Não encontrado`);
- só achou em outra data, por nome (1 candidato) → Revisão Manual (`Possível par encontrado com divergência de data`);
- achou, mas o banco já foi consumido por outro lançamento → Revisão Manual (`Possível par bancário já consumido por outro lançamento`) — nunca desfaz a conciliação anterior;
- nada encontrado → mantém "Não encontrado no banco", mas "Motivo Não Conciliado" na própria linha explica que nenhum candidato foi achado (2026-07-10-b — não existe mais aba separada).

## Regras de revisão manual

Nunca adivinha. Fica em Revisão Manual quando:

- múltiplos candidatos de mesmo valor/data sem descrição suficiente para desempatar;
- quantidade divergente entre ERP e banco para a mesma descrição;
- indício de duplicidade equivalente não confirmável (quantidade ou concorrência);
- lançamento de Salário/Folha/Férias/Rescisão/13º com valor+data batendo mas sem nome/descrição forte e sem lote NET EMP ativo na data exata (`Remuneração/salário sem nome/descrição forte antes do lote`, 2026-07-10);
- pagamento individual com 1 dia de diferença de data, candidato único, mas sem nome/descrição forte (`Possível par com divergência de data (sem nome/descrição forte)`, 2026-07-10);
- lote NET EMP não fecha em nenhuma das 3 etapas automáticas (total direto, combinação única, nome/descrição), inclusive por divergência de data (2026-07-10);
- ERP sem nenhuma data de pagamento/compensação real, só vencimento (`ERP sem data de pagamento/compensação; vencimento não é usado para conciliação`, 2026-07-10);
- verificação final de "Não encontrado no banco" achou indício mas não segurança suficiente (ver seção acima, 2026-07-10);
- nenhuma evidência segura de correspondência.

O "Motivo Revisão" identifica qual dessas categorias ocorreu.

## Colunas obrigatórias do Resultado.xlsx

Data ERP Usada, Tipo Data ERP, Data de Compensação Original, Vencimento Original, Data Banco, Valor ERP, Valor Banco, Favorecido, Descrição ERP, Descrição Banco, Status, Tipo Conciliação, Observações, Motivo Revisão, Motivo Não Conciliado, Diferença de Dias, ID Lote, Possível Data Banco, Possível Valor Banco, Possível Descrição Banco, Status do Possível Banco, Origem (`ERP`, `Banco` ou `ERP+Banco` — ver abaixo). As 5 colunas novas (`Motivo Não Conciliado`, as 3 `Possível .../Status do Possível Banco`) foram adicionadas em 2026-07-10-b junto com a remoção das abas de diagnóstico.

## Aba única (2026-07-10-b)

Antes eram 4 abas (Resultado, Diagnóstico Revisão Manual, Diagnóstico Lotes NET EMP, Diagnóstico Não Encontrados). Agora só existe **"Resultado"** — toda informação de diagnóstico virou coluna da própria linha (ver acima). O detalhe financeiro completo de cada grupo de lote NET EMP (totais, diferença, resultado de cada etapa) que antes só existia na aba "Diagnóstico Lotes NET EMP" agora só está no log do dia (`logs/`) — decisão deliberada para não perder a informação, mas sem duplicar toda a granularidade em coluna.

## Camada de IA (2ª etapa decisiva de conciliação)

Rodando só depois de TODAS as fases determinísticas acima, dentro de `conciliar()`, antes de `_consolidar_pares_conciliados()`. Provedor: Groq API (`src/ia_cliente_groq.py`), modelo padrão e recomendado `openai/gpt-oss-120b`. Três modos, controlados só por variável de ambiente (`.env`, ver `.env.example` e `src/ia_config.py`):

- `IA_MODO=DESATIVADA` (default): não roda; `COLUNAS_RESULTADO` fica exatamente como sempre foi, sem nenhuma coluna nova.
- `IA_MODO=SOMBRA`: roda a mesma análise/validação de `AUTOMATICO`, mas nunca aplica — só preenche as 6 colunas de auditoria (`COLUNAS_IA`, somada a `COLUNAS_RESULTADO` só nesses 2 modos).
- `IA_MODO=AUTOMATICO`: uma decisão `CONCILIAR` aprovada em todas as revalidações concilia de verdade (`Status="Conciliado"`, `Tipo Conciliação="IA validada pelo Python"`), sem revisão humana.

Elegibilidade (todos simultâneos): `Status=="Revisão Manual"`, `Origem=="ERP"`, `Data ERP Usada` preenchida, `Motivo Revisão` numa lista branca de 7 motivos (`MOTIVOS_ELEGIVEIS_IA` em `src/ia_revisor.py`), e não pertence a nenhum tipo de lote NET EMP. Candidatos bancários: no máximo `IA_MAXIMO_CANDIDATOS` (default 5), valor absoluto exato + até `IA_JANELA_BUSCA_DIAS` (default 5 dias) de diferença de data, nunca de lote reservado nem já consumidos. Resposta da IA sempre estruturada via Structured Outputs (JSON Schema `strict=true`, `{decisao, candidato, confianca, motivo}`). Revalidação do Python antes de aplicar: candidato na lista oferecida, valor exato, banco disponível, banco/ERP não são de lote, confiança ≥ limite do modo ativo (`SOMBRA`=0,70 / `AUTOMATICO`=0,95), e só em `AUTOMATICO` diferença de data ≤ `IA_JANELA_AUTOMATICA_DIAS` (default 1 dia — 2 a 5 dias nunca concilia sozinho automaticamente na v1). Se 2+ ERPs escolherem o mesmo banco, nenhuma das decisões conflitantes é aplicada. Nenhuma exceção da camada de IA derruba `python main.py` — falhas viram `Decisão IA="Erro na consulta à IA"` numa linha específica.

Índice de origem (`_erp_index`/`_banco_index`, internos, nunca exportados) obtido via `linha.name` (verificado: todo call site de `_linha_resultado_erp`/`_linha_resultado_banco` já usa `df_erp.loc[i]`/`df_banco.loc[j]`) — zero call sites alterados para viabilizar a IA, só o corpo dessas duas funções.

Ver `docs/HISTORICO_DECISOES.md` para o histórico completo da decisão e `CLAUDE.md` (seção "Camada de IA") para a lista completa de motivos elegíveis/proibidos.

## Uma linha por par conciliado (2026-07-10-b)

Antes, cada par 1‑para‑1 conciliado (correspondência exata, tolerância, duplicidade idêntica/equivalente, desempate por nome, recuperação de "Não encontrado") gerava **duas** linhas espelhadas (`Origem=ERP` e `Origem=Banco`, mesmo conteúdo). Agora gera **uma** linha só, com `Origem="ERP+Banco"`. Implementado em `src/conciliador.py` via `_par_id=(índice_erp, índice_banco)` marcado na origem de cada linha e consolidado por `_consolidar_pares_conciliados()` logo antes de montar o DataFrame final. Grupos de lote NET EMP com mais de 1 lançamento de qualquer lado continuam com uma linha por lançamento (não são pares 1-para-1). Inclui verificação defensiva: um índice ERP ou Banco associado a mais de um par vira Revisão Manual (`Mesmo lançamento ERP/Banco foi associado a mais de um par possível`) em vez de escolher um sozinho — validado que nunca dispara nos dados reais (0 ocorrências no log).

## Testes criados

Pasta `tests/` (pytest), 103 testes (61 das regras determinísticas + 42 da camada de IA) distribuídos em 16 arquivos:

- `test_linha_name_preserva_indice.py`, `test_ia_config.py`, `test_ia_cliente_groq.py`, `test_ia_revisor_candidatos.py`, `test_regra12_ia_decisiva.py` — camada de IA (ver seção "Camada de IA" acima e `docs/HISTORICO_DECISOES.md`).

Arquivos das regras determinísticas (um por regra do CLAUDE.md):

- `test_regra1_data_erp.py` — prioridade Data de compensação vs Vencimento (função genérica) + integração real de `ler_erp()` provando que Vencimento nunca é usado e que uma linha só-com-vencimento é preservada sem Data ERP Usada (2026-07-10).
- `test_regra2_banco.py` — débitos/créditos e valor absoluto (com OFX sintético).
- `test_regra3_conciliacao_individual.py` — par único, desempate por nome, Revisão Manual sem sinal.
- `test_regra4_tarifas_repetidas.py` — duplicidade idêntica individual.
- `test_regra5_pix_individual.py` — PIX/TED/DOC nunca viram lote.
- `test_regra6_lote_net_emp.py` — reserva de lote, total direto, Revisão Manual quando ERP não alcança o banco, "lote claro" (NET EMPRESA genérico não vira lote), proteção reativa do ERP contra coincidências, e (2026-07-10) tolerância de data separada (lote sem tolerância/divergência de data, individual 1 dia com nome forte) e trava de remuneração em par único (sem nome/sem lote ativo → Revisão Manual; sem nome/com lote ativo → adiado; com nome → concilia).
- `test_regra7_status_permitidos.py` — só os 4 status aparecem.
- `test_regra8_combinacao_lote.py` (substituiu `test_regra8_apoio_lote_manual.py` em 2026-07-09, quando a seleção manual foi removida) — busca de combinação única (`_buscar_combinacao_unica_centavos`), detecção de identificador individual (`_banco_tem_identificador_individual`), combinação única fechando o lote automaticamente, múltiplas combinações mantendo Revisão Manual, banco genérico sem combinação, e a Etapa C (nome/descrição) resolvendo e não resolvendo.
- `test_regra9_recuperacao_nao_encontrado.py` (2026-07-10, atualizado em 2026-07-10-b para aba única) — verificação final de "Não encontrado no banco": par único com nome forte concilia (casos reais Mauro Vagner/Heros Rampazzo, mesclados numa única linha `Origem="ERP+Banco"`), múltiplos bancos possíveis mantém Revisão Manual, banco já consumido por outro lançamento (lote) nunca é trocado — só registrado nas colunas "Possível .../Status do Possível Banco" da própria linha —, e um ERP sem candidato nenhum tem "Motivo Não Conciliado" preenchido, nunca em branco.
- `test_regra10_desempate_grupo.py` (novo, 2026-07-10-c) — pareamento por nome em grupos de mesmo valor/data (e dentro da tolerância de 1 dia): valor/data único conciliando direto; grupo de 4 ("Distribuição de Lucros") conciliando corretamente tanto por data exata quanto pela fase de tolerância (regressão do bug real relatado — combinações cruzadas do tipo "Ricardo Mouro x Raphael Pekly"); grupo parcialmente resolvido (3 seguros + 1 ambíguo); empate de nome entre múltiplos candidatos; "primeiro nome apenas" não conciliando com risco real de ambiguidade; ausência de duplicidade de par no Resultado; Resultado.xlsx com 1 aba só.
- `test_regra11_valor_data_unicos.py` (novo, 2026-07-10-d) — "FGTS" nunca é lote (`_classificar_tipo_lote`); caso real FGTS - Rescisão Daniel Lemos conciliando por "Valor e data" sem nenhum nome em comum; ERP único + banco único com descrição totalmente diferente; ERP com 2 bancos do mesmo valor/data (Revisão Manual); 2 ERP com 1 banco do mesmo valor/data (Revisão Manual); Resultado sem pares duplicados; Resultado.xlsx com 1 aba; e 3 testes unitários diretos de `_verificar_possiveis_pares_nao_encontrados` (concilia sem nome quando único, não concilia com múltiplos candidatos, não concilia quando banco já consumido).

`tests/conftest.py` fornece os builders (`construir_df_erp`/`construir_df_banco`) e um logger silencioso. Ver `tests/README_TESTES.md` para instruções.

## Pontos que já estão funcionando

- Prioridade Data de compensação > Vencimento, linha a linha.
- Filtro de débitos e de período do banco.
- Conciliação individual (par único, tolerância de datas, desempate por nome).
- Duplicidade idêntica individual (tarifas repetidas), validada com dados reais (ex.: 8 tarifas do mesmo valor/data no mesmo dia).
- Lote NET EMP por total direto, incluindo o caso de **múltiplos lotes do mesmo tipo no mesmo dia** resolvidos sem reaproveitar item do ERP entre eles (validado com dados reais).
- Lote claro (marcador + tipo específico) e a reserva simétrica do ERP: um "PAG COBRANCA NET EMPRESA"/"PAGTO ELETRON COBRANCA PAG COBRANCA NET EMPRESA" real que antes virava um "lote genérico" com diferença de R$ 44.000,00 (misturando DHL, Safetyfyi, ASCORP e Consultoria Claudio, sem relação nenhuma entre si) concilia cada um individualmente por valor e data, e "Consultoria Claudio" aparece corretamente como "Não encontrado no banco".
- Busca automática de combinação exata única (2026-07-09), validada com testes sintéticos: fecha sozinha quando existe 1 combinação, nunca adivinha quando existem 2+.
- Conciliação individual antes do lote NET EMP (2026-07-10): o ERP de Salário/Folha/Férias/Rescisão/13º agora tenta a via individual (valor+data, nome/descrição, tolerância) antes de entrar no pool do lote — só fica retido para o lote se ficar ambíguo sem sinal seguro. Validado end-to-end com `python main.py` nos dados reais: o grupo de Salário/Folha de 06/05/2026, que antes tinha 29 candidatos do ERP (R$ 54.569,83) contra 12 do banco (R$ 34.760,52) e ficava em Revisão Manual por "múltiplas combinações possíveis", agora identifica 9 desses candidatos como pagos individualmente fora do lote (PIX nomeado, cada um com o nome do funcionário na descrição do banco) — restam exatamente 20 candidatos cuja soma (R$ 34.760,52) bate exatamente com o banco, fechando por total direto. Revisão Manual do arquivo inteiro caiu de 41 para 0 linhas nessa execução.
- Etapa C (nome/descrição dentro do lote), para quando o banco excepcionalmente traz identificador individual — validada com testes sintéticos; nos dados reais atuais, todo o NET EMP é genérico (sem nome), então essa etapa nunca é acionada na prática hoje.
- **Não existe mais nenhuma forma de marcação manual** (a aba "Apoio Lote NET EMP" e a seleção SIM/NÃO foram removidas em 2026-07-09) — a conciliação do lote é 100% automática.
- Leitura de OFX com fallback de encoding e correção de cabeçalho com linha em branco.
- Filtro de período detectado automaticamente a partir do texto "Período: ..." do relatório.
- Aba única "Resultado" (2026-07-10-b — antes eram 4 abas), com todo o diagnóstico embutido em colunas.
- Uma linha por par ERP × Banco conciliado, sem espelhamento (2026-07-10-b), validada em produção: 828 pares mesclados (`Origem="ERP+Banco"`) no arquivo real de 921 lançamentos do ERP × 870 do banco, 0 conflitos de índice detectados pela verificação defensiva.
- Suíte de testes automatizados cobrindo as 10 regras principais (61 testes, 11 arquivos).
- Verificação final de "Não encontrado no banco" concilia por valor+data único mesmo sem nome, e "FGTS" nunca é tratado como lote NET EMP (2026-07-10-d) — corrigido caso real (FGTS - Rescisão Daniel Lemos, batendo com um depósito à Caixa sem nenhum nome em comum); validado end-to-end com `python main.py`: Revisão Manual caiu de 19 para 15 linhas.
- Pareamento por nome em grupos de mesmo valor/data também na fase de tolerância de 1 dia (2026-07-10-c) — corrigido bug real de combinações cruzadas ("Distribuição de Lucros" para 4 pessoas indo tudo para Revisão Manual com pares errados); validado end-to-end com `python main.py`: Revisão Manual do arquivo real caiu de 29 para 19 linhas, todas por motivos genuínos.
- Tolerância de data separada e trava de remuneração em par único (2026-07-10), validadas end-to-end com `python main.py` nos dados reais.
- Vencimento nunca mais usado para conciliar e verificação final de "Não encontrado no banco" (2026-07-10), validadas com `python main.py` num arquivo real de 921 lançamentos do ERP (jan-mai/2026): 0 linhas dependiam de vencimento (todo o arquivo tinha "Data de confirmação" preenchida); a verificação final avaliou 9 candidatos a "Não encontrado no banco" e não recuperou nenhum — todos genuinamente não tinham nenhum lançamento bancário com valor, data ou nome compatível (agora documentado em "Motivo Não Conciliado" na própria linha, em vez de ficar sem explicação). Total de linhas do Resultado (após a mesclagem de pares em 2026-07-10-b, o pareamento por nome na tolerância em 2026-07-10-c, e a conciliação por valor+data único sem nome em 2026-07-10-d): 956 — Conciliado: 931; Revisão Manual: 15 (8 duplicidade sem nome, 4 tolerância sem evidência, 3 remuneração sem nome antes do lote, 0 empate de nome); Não encontrado no banco: 10; Somente banco: 0.

## Pontos que ainda precisam de atenção

- **Duplicidade equivalente individual** (NF diferente, mesmo fornecedor): já apareceu em execução real (4 ocorrências no arquivo de jan-mai/2026 processado em 2026-07-10) — regra confirmada em produção, não é mais só teoria sintética.
- Não há teste automatizado cobrindo `leitor_banco.py` lendo um arquivo Excel real do GestãoClick como banco (só o núcleo de conciliação, a leitura de OFX sintético e agora `ler_erp()` com Excel sintético estão cobertos) — mudanças na detecção de cabeçalho/colunas do Excel do banco não têm rede de segurança automática ainda.
- A busca de combinação (`_buscar_combinacao_unica_centavos`, meet-in-the-middle) é segura e rápida até 40 candidatos por grupo; acima disso, o grupo é tratado como "grupo grande demais para busca automática" em vez de arriscar uma busca incompleta ou lenta — ainda não apareceu um caso real com mais de 40 candidatos num único grupo.
- `requirements.txt` já teve problema de encoding (UTF-16 por engano) corrigido numa rodada de documentação anterior — vale conferir se ao reabrir no Excel/editor ele não volta a ser salvo errado.

## O que o Claude nunca deve fazer em futuras alterações

- Nunca criar exceção por fornecedor, descrição ou valor específico (ex.: "se for IB EXTINTORES...", "se for MOURO SOLUÇÕES..."). Sempre corrigir a regra geral.
- Nunca recriar o projeto do zero ou alterar a estrutura de pastas sem autorização explícita.
- Nunca remover uma regra que já funciona para "consertar" outra — as regras se acumulam, não se substituem, a menos que o usuário peça explicitamente a mudança.
- Nunca marcar algo como "Conciliado" sem uma correspondência inequívoca — na dúvida, Revisão Manual.
- Nunca deixar um crédito do banco entrar na conciliação (deve ser filtrado antes).
- Nunca deixar um lançamento NET EMP/EMPR competir por valor+data na conciliação individual.
- Nunca escolher sozinho uma combinação de valores do lote quando existir mais de uma possível (2+ combinações = Revisão Manual, sempre) — nem "chutar" a mais provável.
- Nunca reintroduzir marcação manual (aba de apoio, coluna SIM/NÃO) para a conciliação do lote NET EMP sem o usuário pedir explicitamente — essa lógica foi removida por decisão explícita em 2026-07-09.
- Nunca bloquear o ERP de remuneração/férias/rescisão/13º da conciliação individual de forma preventiva (antes de tentar) sem pedido explícito do usuário — desde 2026-07-10 a proteção é reativa (só retém depois de tentar sem sucesso); voltar ao bloqueio cego reintroduziria o problema que essa mudança resolveu (candidatos pagos fora do lote inflando o pool e causando "múltiplas combinações" à toa).
- Nunca deixar um par único (1 ERP x 1 Banco) de remuneração/salário/férias/rescisão/13º conciliar automaticamente só por valor+data sem nome/descrição forte — regra explícita de 2026-07-10, existe justamente para não "roubar" candidatos legítimos do lote por coincidência.
- Nunca dar tolerância de data ao lote NET EMP (deve ser sempre data exata) nem voltar a tolerância de 3 dias para pagamentos individuais sem pedido explícito do usuário — reduzida para 1 dia (e com exigência de nome/descrição forte) em 2026-07-10.
- Nunca voltar a usar Vencimento como fallback de Data ERP Usada sem pedido explícito do usuário — removido em 2026-07-10; uma linha só-com-vencimento deve continuar preservada (não descartada) e marcada Revisão Manual com motivo específico.
- Nunca trocar automaticamente a conciliação de um lançamento do banco já usado para "resgatar" um ERP marcado como "Não encontrado no banco" — a verificação final (2026-07-10) só concilia candidatos ainda pendentes; um banco já consumido vira só um registro de diagnóstico (`Possível par bancário já consumido por outro lançamento`), nunca uma troca automática.
- Nunca ajustar um teste em `tests/` só para fazê-lo passar sem entender por que ele quebrou — investigar a causa raiz e corrigir a regra geral primeiro.
- Nunca alterar `src/` sem rodar `pytest` depois para confirmar que nada regrediu.
- Nunca deixar a camada de IA analisar ou aplicar decisão sobre um lançamento que não esteja `Status=="Revisão Manual"` — ela nunca reabre, desfaz ou substitui uma conciliação (ou "Não encontrado"/"Somente banco") já decidida pelas regras determinísticas.
- Nunca ampliar a lista branca de motivos elegíveis (`MOTIVOS_ELEGIVEIS_IA`) ou reduzir a confiança mínima/janela de aplicação automática sem pedido explícito do usuário — os limites atuais (`SOMBRA`=0,70/5 dias, `AUTOMATICO`=0,95/1 dia) foram calibrados a pedido dele especificamente para serem conservadores na primeira versão.
- Nunca colocar constante de IA (modo, chave, modelo, janelas, confiança) em `src/utils.py` ou fixa no código — tudo vem de variável de ambiente via `src/ia_config.py`, decisão explícita do usuário.
- Nunca logar o valor de `GROQ_API_KEY` em nenhuma linha, em nenhum nível de log.
- Nunca aplicar uma decisão `CONCILIAR` da IA em `IA_MODO=AUTOMATICO` sem passar por todas as revalidações do Python (candidato oferecido, valor exato, banco disponível, não é lote, confiança do modo, janela de 1 dia, ausência de conflito) — e nunca aplicar quando 2+ lançamentos disputam o mesmo banco, mesmo que um tenha confiança maior que o outro.
