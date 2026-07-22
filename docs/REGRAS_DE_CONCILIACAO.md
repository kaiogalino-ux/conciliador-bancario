# Regras de conciliação — visão de negócio

Este documento descreve **o que** o sistema faz, em linguagem de negócio, sem entrar em código ou nomes de arquivo. Para detalhes técnicos, ver `docs/ESTADO_ATUAL_DO_PROJETO.md` e `CLAUDE.md`.

## 1. Qual data do ERP é usada

1. Se existir **Data de compensação** preenchida, ela é usada — sempre, mesmo que outra data também esteja preenchida.
2. Se não existir, usa-se a **Data de pagamento/baixa/confirmação**.
3. **Vencimento nunca é usado** para conciliar (regra de 10/07/2026 — antes era o último recurso). Um lançamento sem nenhuma data de pagamento/compensação/confirmação real fica sem data e não tenta casar com o banco de jeito nenhum — vai direto para Revisão Manual, com um aviso claro de que só havia vencimento.

Essa escolha é feita lançamento por lançamento, nunca "para a planilha inteira".

## 2. O que entra na conciliação, do lado do banco

- Só **saídas de dinheiro** (débitos). Entradas — PIX recebido, TED recebida, depósito, qualquer valor positivo — são descartadas antes de começar a comparar.
- Só lançamentos dentro do **período do relatório do ERP**. Lançamentos de outros meses no extrato bancário são ignorados.
- Valores são sempre comparados em **módulo** (valor absoluto): R$ 500 no ERP e -R$ 500 no banco são o mesmo valor.

## 3. Como a conciliação decide

A regra de ouro é: **nunca adivinhar**. Um lançamento só é marcado como Conciliado quando existe uma correspondência clara e sem ambiguidade. Na dúvida, fica em Revisão Manual para uma pessoa decidir.

A conciliação tenta, nesta ordem:

1. **Par único** — 1 lançamento do ERP e 1 do banco, mesmo valor e mesma data → concilia direto. **Exceção (2026-07-10):** se o lançamento do ERP for de salário/férias/rescisão/13º, valor+data sozinhos não bastam — precisa também de nome/descrição compatível (ver seção 4).
2. **Duplicidade idêntica** — vários lançamentos repetidos, com a mesma descrição e a mesma quantidade dos dois lados (ex.: várias tarifas bancárias de R$ 9,80 no mesmo dia) → concilia cada um individualmente, um a um.
3. **Desempate por nome/descrição** — quando há mais de um lançamento com o mesmo valor e data (ou o mesmo valor dentro da tolerância de 1 dia, ver item 6), mas descrições diferentes que permitem saber quem é quem (ex.: nome da pessoa aparece nos dois lados, mesmo que abreviado — "SILV" é reconhecido como "SILVA" truncado) → concilia cada par certo individualmente, mesmo em grupos de 3, 4 ou mais nomes (ex.: distribuição de lucros para várias pessoas no mesmo valor/data); resolve os pares seguros e deixa só os realmente ambíguos (empate de nome) em Revisão Manual — nunca tudo o grupo de uma vez (10/07/2026, ver seção 6 abaixo).
4. **Duplicidade equivalente** — quando o ERP identifica o lançamento por número de nota fiscal/documento, mas o banco não mostra esse número (ex.: "Fornecedor X - NF 199" e "NF 200" no ERP, e só "Fornecedor X" duas vezes no banco) → concilia individualmente, desde que a quantidade seja igual dos dois lados e não haja outro candidato concorrente.
5. **Lote de salário/férias/rescisão (NET EMP)** — o **banco** de um lote NET EMP/EMPR nunca é comparado um a um; mas um lançamento do **ERP** desse tipo (salário, férias, rescisão, 13º) tenta primeiro a via individual normal (par 1, nome/descrição, tolerância) — só entra na etapa de lote se não encontrar nenhum par seguro. O sistema então tenta fechar o lote automaticamente com quem sobrou (total direto, depois combinação exata de valores, depois nome/descrição se o banco trouxer). Nunca depende de marcação manual.
6. **Tolerância de data** — só para pagamentos comuns (nunca lote NET EMP): até 1 dia de diferença entre a data do ERP e a do banco (reduzido de 3 para 1 dia em 2026-07-10), e só concilia sozinho quando há também nome/descrição compatível — proximidade de data sozinha nunca é suficiente. Quando há vários candidatos do mesmo valor dentro dessa janela (não só 1 ERP x 1 Banco), o mesmo algoritmo de pareamento por nome do item 3 é usado, restrito a quem está de fato dentro da tolerância — nunca escolhe "o primeiro da lista" (correção de 10/07/2026: um caso real de distribuição de lucros para 4 pessoas, todas no mesmo valor e datas próximas, estava gerando combinações cruzadas erradas por causa dessa escolha ingênua).
7. **Sem nenhuma das anteriores** → fica em Revisão Manual, com o motivo explicado.

## 4. Lote de salário/férias/rescisão (NET EMP / NET EMPR)

Alguns pagamentos (salário, férias, rescisão, 13º) chegam no banco como um **valor único em lote** (ex.: "PGTO SALARIO VIA NET EMP"), enquanto no ERP aparecem como vários lançamentos separados (um por funcionário).

- Só é tratado como lote quando a descrição do banco tem, ao mesmo tempo, um marcador de NET EMP/EMPR/EMPRESA **e** um termo que diga claramente o tipo (salário, férias, rescisão, folha ou 13º). Uma descrição como "PAG COBRANCA NET EMPRESA" ou "PAGTO ELETRON COBRANCA" — sem nenhuma dessas palavras — **não** é lote; é um pagamento comum e segue a conciliação individual normal.
- **(10/07/2026, versão d)** Um lançamento com "FGTS" no texto **nunca** é considerado lote, mesmo contendo "rescisão" ou "13" (ex.: "FGTS - Rescisão Fulano", "FGTS - 13ª parcela") — FGTS é sempre depositado direto na Caixa Econômica Federal, nunca pago junto com a folha da empresa.
- Esses lançamentos do banco **nunca** são comparados individualmente por valor e data — mesmo que, por coincidência, um deles bata exatamente com um único lançamento do ERP.
- Do lado do ERP, um lançamento de salário/férias/rescisão/13º **tenta primeiro a conciliação individual normal** contra o banco que não é lote (um funcionário pago fora do lote, por PIX nomeado, é conciliado corretamente por aí) — **mas** um par único desse tipo só concilia direto quando há também nome/favorecido/descrição forte compatível; valor+data sozinhos nunca "roubam" um candidato do lote por coincidência (regra de 10/07/2026). Sem esse sinal: se existir um lote bancário claro do mesmo tipo na **mesma data exata**, o lançamento fica retido para a etapa de lote (em vez de virar "Revisão Manual"); senão, tanto o ERP quanto o pagamento comum que coincidiu vão para Revisão Manual com o motivo "Remuneração/salário sem nome/descrição forte antes do lote".
- **Lote NET EMP não usa tolerância de data nenhuma** (regra de 10/07/2026, antes era 3 dias): a Data ERP Usada do candidato precisa ser exatamente igual à data do lote bancário. Quando existem candidatos do tipo certo mas em outra data, o grupo fica em Revisão Manual com o motivo "Divergência de data para lote NET EMP" em vez do motivo genérico de total insuficiente.
- Eles são classificados por tipo: Salário/Folha, Férias, Rescisão ou 13º salário.
- O sistema tenta fechar o lote automaticamente, sempre nesta ordem, sem nunca adivinhar:
  1. **Total direto** — soma tudo que sobrou do ERP daquele tipo/data e compara com a soma de tudo que sobrou do banco. Bate exatamente → concilia tudo.
  2. **Combinação exata única** — se o total do ERP for maior que o do banco, o sistema procura sozinho um subconjunto dos candidatos cuja soma feche exatamente o total do banco. Só concilia quando existe **exatamente uma** combinação possível — os que ficaram de fora dessa combinação são marcados "Não encontrado no banco", já que a soma exata prova que não pertencem a esse lote específico. Havendo 2 ou mais combinações possíveis, o sistema nunca escolhe sozinho: fica em Revisão Manual.
  3. **Nome/descrição** — só tentado quando o banco excepcionalmente traz um nome, CPF ou documento junto da descrição do lote (nunca para bancos genéricos como "PGTO SALARIO VIA NET EMP" sozinho); só aceita se identificar com segurança todos os lançamentos do banco do grupo.
- Se nenhuma das três formas fechar, todo o grupo fica em Revisão Manual, mostrando o total de cada lado, a diferença e qual etapa falhou.
- **Não existe nenhuma marcação manual.** O sistema nunca pede para o usuário escolher, numa planilha, quais lançamentos entram no lote — ou fecha sozinho com evidência matemática/de nome, ou fica em Revisão Manual para conferência humana direto no relatório.
- Pode haver **mais de um lote do mesmo tipo no mesmo dia** — o sistema resolve lote por lote, sem usar o mesmo lançamento do ERP em mais de um lote.

## 5. PIX, TED e DOC individuais

Transferências individuais (PIX, TED, DOC) com o nome de uma pessoa ou empresa específica **nunca** entram na regra de lote, mesmo que haja várias no mesmo dia. Elas são sempre conciliadas pela via individual: por valor e data, ou por desempate de nome quando há mais de uma com o mesmo valor.

## 6. Verificação final antes de "Não encontrado no banco" (10/07/2026)

Antes de desistir de um lançamento do ERP (marcá-lo "Não encontrado no banco"), o sistema dá uma última checada: existe algum lançamento no extrato bancário — usado em outra conciliação ou não — com o mesmo valor e a mesma data?

- **Achou exatamente 1, ainda disponível, e nenhum outro ERP também disputa esse mesmo banco** → concilia (nunca é "Não encontrado" sem necessidade). **(10/07/2026, revisado em 10/07/2026 — versão d)** Não precisa mais de nome/descrição parecido: valor e data já sendo únicos dos dois lados é evidência suficiente. Quando o nome também bate, o resultado só ganha um rótulo mais rico ("Valor, data e nome" em vez de "Valor e data").
- **Achou mais de 1 candidato pelo mesmo valor e data (do lado do banco), ou o único candidato também é reivindicado por outro ERP** → vira Revisão Manual, avisando que existe mais de uma possibilidade e o sistema nunca escolhe sozinho.
- **Não achou nada na mesma data, mas achou 1 com o mesmo valor e nome forte em outra data** → vira Revisão Manual, avisando que pode ser o mesmo pagamento com a data diferente.
- **Achou, mas esse lançamento do banco já fechou com outro item do ERP** → vira Revisão Manual avisando do conflito — o sistema **nunca desfaz** uma conciliação já feita para tentar "roubar" o banco de outro lugar.
- **Não achou nada por nenhum critério** → continua "Não encontrado no banco", mas a coluna "Motivo Não Conciliado" da própria linha explica que a busca foi feita e não achou nada (não existe mais aba própria — ver regra de aba única).

## 7. Situações que ficam em Revisão Manual

- Mais de um lançamento com o mesmo valor e data, sem descrição suficiente para saber qual é qual.
- Quantidade diferente entre ERP e banco para a mesma descrição (ex.: 3 tarifas no ERP contra 4 no banco).
- Indício de que dois lançamentos são o mesmo fornecedor (duplicidade equivalente), mas sem certeza suficiente para confirmar sozinho.
- Lançamento de salário/férias/rescisão/13º com valor+data batendo mas sem nome/descrição forte, e sem lote NET EMP ativo na mesma data para ficar disponível (2026-07-10).
- Pagamento comum com 1 dia de diferença de data, candidato único, mas sem nome/descrição forte (2026-07-10).
- Lote de salário/férias/rescisão que não fecha em nenhuma das 3 formas automáticas (total direto, combinação única, nome/descrição), inclusive por divergência de data (2026-07-10).
- ERP sem nenhuma data de pagamento/compensação real, só vencimento — vencimento nunca é usado para conciliar (2026-07-10).
- A verificação final (item 6 acima) achou algum indício de possível par, mas não segurança suficiente para conciliar sozinho.
- Qualquer situação sem nenhuma evidência segura.

## 8. Resultados possíveis

Todo lançamento termina em um destes quatro status, nunca em outro:

- **Conciliado** — encontrou o par correspondente com segurança.
- **Revisão Manual** — há indício, mas não segurança suficiente; precisa de conferência humana.
- **Não encontrado no banco** — existe no ERP, mas não foi localizado nenhum lançamento correspondente no banco (mesmo depois da verificação final do item 6).
- **Somente banco** — existe no extrato do banco, mas não há nada correspondente no ERP.

## 9. Onde ver o resultado

O arquivo `Resultado.xlsx` tem **uma única aba**, "Resultado" (revisado em 10/07/2026 — antes eram 4 abas). Cada lançamento (ou par conciliado) aparece em uma linha, com todo o diagnóstico que antes vivia em abas separadas agora embutido em colunas:

- **Motivo Revisão** — por que um lançamento está em Revisão Manual.
- **Motivo Não Conciliado** — por que um lançamento ficou "Não encontrado no banco" ou "Somente banco" (nunca fica em branco).
- **Possível Data/Valor/Descrição Banco** e **Status do Possível Banco** — quando a verificação final (item 6) achou algum candidato de banco parecido, mesmo sem confirmar.
- O detalhe financeiro completo de cada lote NET EMP (totais, diferença, resultado de cada tentativa) continua no arquivo de log do dia (`logs/`), para auditoria.

## 9.1 Uma linha por par conciliado (10/07/2026)

Cada par ERP × Banco efetivamente conciliado (correspondência 1‑para‑1) aparece em **uma única linha**, nunca duas linhas espelhadas (uma "do lado ERP", outra "do lado Banco"). Essa linha traz `Origem = "ERP+Banco"`. Duplicidades reais (ex.: duas tarifas idênticas de R$ 9,80 no mesmo dia) continuam em linhas separadas, porque são pares diferentes — só a repetição artificial do mesmo par é eliminada. Grupos de lote NET EMP com mais de um lançamento de qualquer lado continuam com uma linha por lançamento, como sempre.

## 10. Princípio geral

Nunca se cria uma regra especial para um fornecedor, cliente ou valor específico. Se um caso não está conciliando corretamente, a correção é sempre na regra geral que se aplica a todos os casos parecidos — nunca uma exceção pontual.
