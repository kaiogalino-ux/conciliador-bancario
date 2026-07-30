# Testes automáticos do Conciliador Bancário

## Para que servem

Estes testes existem para que as regras de negócio já aprovadas (documentadas
em [`CLAUDE.md`](../CLAUDE.md)) não sejam esquecidas ou quebradas conforme o
código evolui. O projeto já passou por vários ajustes finos de conciliação
(prioridade de data, lote NET EMP, desempate por nome, etc.) — sem uma rede de
segurança automática, é fácil uma mudança nova reintroduzir um problema que já
tinha sido corrigido antes.

Cada arquivo de teste protege uma das regras obrigatórias do `CLAUDE.md`. Se
um teste falhar depois de uma alteração, é sinal de que essa alteração quebrou
uma regra que já funcionava — **a regra geral deve ser corrigida, nunca uma
exceção deve ser criada para "consertar" o teste** (mesma diretriz de
"nunca corrigir por fornecedor específico" do `CLAUDE.md`).

## Como rodar os testes

Instale as dependências (o `pytest` está em `requirements-dev.txt`, não em
`requirements.txt`) e rode a partir da pasta `backend/`:

```powershell
pip install -r backend\requirements-dev.txt
cd backend
pytest
```

Para ver mais detalhe (nome de cada teste, não só um resumo):

```bash
pytest -v
```

Para rodar só os testes de uma regra específica, por exemplo o lote NET EMP:

```bash
pytest tests/test_regra6_lote_net_emp.py -v
```

Os testes **não** leem nem escrevem nada em `dados/`, `resultado/` ou `logs/`
— eles chamam as funções de `src/` diretamente com dados fabricados na hora
(veja `tests/conftest.py`), então são rápidos e não interferem nos seus
arquivos reais.

## Quais regras cada arquivo protege

| Arquivo | Regra do CLAUDE.md | O que verifica |
|---|---|---|
| `test_regra1_data_erp.py` | Data de compensação | Se "Data de compensação" estiver preenchida, ela é sempre usada como Data ERP Usada; "Vencimento" só é usado quando a compensação está vazia — linha a linha, nunca pela coluna inteira. |
| `test_regra2_banco.py` | Débitos do banco | O banco só considera débitos/saídas (créditos como PIX/TED recebidos e depósitos são descartados antes da conciliação e nunca aparecem como "Somente banco"); a comparação de valor usa sempre o valor absoluto. |
| `test_regra3_conciliacao_individual.py` | Duplicidade com descrição diferente | Par único de mesmo valor/data concilia direto; duplicidade é desempatada por nome/descrição quando há sinal suficiente; sem sinal nenhum, fica em Revisão Manual (nunca adivinha). |
| `test_regra4_tarifas_repetidas.py` | Tarifas repetidas | Tarifas com mesma data/valor/descrição/quantidade nos dois lados conciliam uma a uma, sem resumir em uma linha de grupo; quantidade diferente não concilia como idêntica. |
| `test_regra5_pix_individual.py` | PIX individual | PIX/TED/DOC nunca são candidatos à regra de lote; PIX ambíguos (mesmo valor/data) são resolvidos individualmente por nome. |
| `test_regra6_lote_net_emp.py` | Lote NET EMP | "PGTO ... VIA NET EMP/EMPR" nunca concilia sozinho por valor e data (mesmo quando bate por coincidência); fica reservado para lote; concilia por lote (total direto) quando a soma do ERP restante bate exatamente com a soma do banco na mesma data; fica em Revisão Manual quando o ERP é menor que o banco; um marcador NET EMPRESA sem termo de tipo (ex.: "PAG COBRANCA NET EMPRESA") não vira lote; um lançamento do ERP de salário não pode ser consumido por coincidência de valor+data antes da etapa de lote. |
| `test_regra7_status_permitidos.py` | Status permitidos | A coluna "Status" nunca tem nenhum valor além de Conciliado, Revisão Manual, Não encontrado no banco e Somente banco. |
| `test_regra8_combinacao_lote.py` | Combinação automática do lote NET EMP | Quando o total do ERP é maior que o do banco, busca sozinho uma combinação exata de valores (nunca adivinha): fecha automaticamente quando existe exatamente 1 combinação; mantém Revisão Manual quando existem 2+ (múltiplas) ou nenhuma; tenta nome/descrição só quando o banco traz identificador individual; não existe nenhuma marcação manual. |

## Como usar antes de futuras alterações

1. **Antes** de mexer em `src/conciliador.py`, `src/leitor_erp.py`,
   `src/leitor_banco.py` ou `src/utils.py`, rode `pytest` e confirme que tudo
   passa — esse é o seu ponto de partida conhecido.
2. Faça a alteração.
3. Rode `pytest` de novo.
   - Se tudo passar, a alteração não quebrou nenhuma regra já protegida.
   - Se algum teste falhar, leia o nome do teste e o arquivo (a tabela acima
     diz qual regra é) — ele aponta exatamente qual comportamento aprovado
     regrediu.
4. Corrija a **regra geral** no código-fonte até o teste voltar a passar.
   Nunca ajuste o teste para "passar a qualquer custo", a menos que a própria
   regra de negócio tenha mudado de propósito (nesse caso, avise antes).
5. Ao adicionar uma regra nova de conciliação, adicione também um teste novo
   (siga o padrão `test_regraN_nome.py` e o guia de `tests/conftest.py`) para
   que ela também fique protegida daqui em diante.
