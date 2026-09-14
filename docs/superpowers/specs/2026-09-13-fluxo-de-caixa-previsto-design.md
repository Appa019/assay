# Fluxo de caixa previsto — entrada × saída, 6 meses

Data: 2026-09-13 · Status: aprovado para implementação

## Problema

O app só sabe olhar para trás. `/extrato` mostra o mês fechado ou em
andamento, e a seta de avançar mês fica desabilitada no mês corrente — então
as parcelas futuras, que **já estão gravadas** em `cashflow_entry` com
`occurred_on` à frente, são invisíveis até o mês chegar. Não existe nenhuma
tela que responda "quanto sobra nos próximos meses".

Falta também o conceito de recorrência: salário, aluguel e assinatura só
viram linha quando acontecem. Sem isso não há "entrada prevista".

## Decisões do cliente

1. **Previsão é cadastro, não estatística.** Nenhuma média histórica entra na
   conta: o número vem de compromissos registrados. Gasto variável fica de
   fora — a sobra exibida é teto, não expectativa.
2. **Horizonte de 6 meses** — mês corrente + 5 à frente.
3. **Cadastro só pelo consultor.** Nenhum formulário na interface.

## Arquitetura

### Recorrência é configuração, não lançamento

`Recurrence` é uma tabela de configuração. A previsão recalcula a cada
leitura, como `card_service` já faz com fatura ("invoices are NEVER stored").

Materializar 6 linhas futuras em `cashflow_entry` foi rejeitado: duplicaria o
lançamento no dia em que a despesa real acontece, exigiria reescrever o futuro
a cada mudança de valor, e poluiria o `/extrato` — que hoje é só fato
consumado — com dinheiro que não se moveu.

### A matemática do mês

Uma regra, válida para passado, presente e futuro:

    total(mês, kind) = Σ lançamentos reais do mês
                     + Σ recorrências do mês NÃO cumpridas

"Cumprida" = existe lançamento real no mês com o mesmo `kind` e a mesma
`category` (normalizada), casado **um-para-um**: duas assinaturas recorrentes
com uma já lançada contam 1 real + 1 prevista.

Duas guardas:

- **linhas de parcela nunca casam** (`installment_no` não nulo fica fora do
  pareamento) — senão uma compra parcelada categorizada "lazer" anularia a
  mensalidade recorrente de "lazer";
- **só carteira `conta`**. VR/VA são benefício alimentação, nunca sobra
  investível, e entram no fluxo como rodapé separado.

### Competência, não caixa

Parcela conta no mês do `occurred_on`. **Fatura não vira linha de saída** — os
R$ 1.240 de parcelas do mês seriam somados de novo como "fatura do cartão". A
fatura aparece como legenda do mês em que vence (`fecha 25/10 · vence 10/11`),
coerente com a regra que já vale no app: pagar fatura nunca é gasto.

### Início da recorrência

`starts_on` nasce no **primeiro dia do mês corrente**, não em hoje. Cadastrar
o aluguel no dia 13 significa "esse é o meu aluguel"; começar hoje derrubaria
o mês atual de toda recorrência cujo dia já passou, e a tela abriria com a
primeira coluna quebrada. A contagem dobrada não é risco: aluguel já lançado
cumpre a recorrência pela regra de casamento.

### Realizado × pendente

`realized_*` = lançamento real com `occurred_on <= hoje`.
`pending_*` = o resto (lançamento futuro do mês + recorrência não cumprida).
No mês corrente isso separa o que já saiu do que ainda vai sair; nos meses à
frente tudo é pendente.

## Componentes

| Unidade | Responsabilidade |
|---|---|
| `app/models/recurrence.py` | tabela `Recurrence` (criada por `create_all`) |
| `app/schemas/recurrence.py` | Create/Update/Read |
| `app/schemas/forecast.py` | `Forecast`, `ForecastMonth`, `ForecastLine`, `ForecastInvoice` |
| `app/services/recurrence_service.py` | CRUD + ocorrências de um mês |
| `app/services/forecast_service.py` | `build_forecast` — a matemática acima |
| `app/routers/recurrences.py` | `/api/recurrences` |
| `GET /api/cashflow/forecast` | 6 meses prontos para a tela |
| `chat_service` | ordens + `curl` para o consultor cadastrar |
| `/extrato?aba=fluxo` | a tela |

## Tela

Sub-aba em `/extrato`, com o mesmo `TabRail` do `/investimentos` — o `nav.ts`
é fechado em quatro abas de propósito ("fewer, fatter tabs beat eight thin
ones on a phone").

Seis meses empilhados. Cada mês traz entrada e saída como duas barras finas
numa **escala compartilhada entre todos os meses**: é o que faz o aperto
saltar aos olhos e o alívio aparecer no mês em que a última parcela cai.
Sobra em número grande à direita, vermelha quando negativa. Tocar abre a
composição (recorrências com o dia, parcelas com `3/10`, faturas vencendo).

## Testes

- mês curto: `day_of_month` 31 cai no dia 30/28;
- `ends_on` encerra a recorrência (o mês seguinte alivia);
- salário já lançado não conta em dobro;
- parcela não anula recorrência da mesma categoria;
- VR/VA fora do fluxo;
- fatura entra como legenda, nunca como saída;
- API: 404/422 nas bordas.
