# Cartão de crédito no ledger pessoal — design

> Data: 2026-09-12 · Status: aprovado em chat, aguardando revisão do spec.
> Escopo: fazer o Assay funcionar como app de rastrear gastos com o cartão
> de crédito como meio de pagamento padrão, sem contar nada em dobro.

## 1. Problema

O cliente vai passar **tudo** no cartão de crédito e quer rastrear tudo que
ganhou e gastou, cartão incluído. O ledger pessoal (`CashflowEntry`) já
registra ganhos e gastos com categoria, data e carteira (`conta`, `vr`, `va`),
mas:

- "cartão" e "crédito" são apelidos de `conta` (`normalize_wallet`): um gasto
  no cartão entra como se o dinheiro saísse do banco na hora;
- não existe fatura, dia de fechamento, vencimento nem parcela;
- nada impede o consultor de lançar "paguei a fatura" como gasto, o que conta
  cada compra duas vezes.

## 2. Decisões (fechadas com o cliente em 2026-09-12)

| # | Decisão | Consequência |
|---|---|---|
| 1 | **Regime de competência.** O gasto no cartão conta no mês da compra, não no mês em que a fatura é paga. | "Saldo do mês" segue sendo ganhos − gastos, agora somando conta e cartão. A fatura é uma visão separada: quanto vai sair da conta e quando. |
| 2 | **Cartão é o padrão.** Gasto em `conta` que não cita meio de pagamento vai para o cartão padrão. "no pix", "no débito", "em dinheiro" tiram do cartão. VR e VA nunca têm cartão. | A regra vive no service (`resolve_card`), não em prompt — vale para consultor, classificador, bot e API. |
| 3 | **Pagar a fatura nunca é gasto.** | Ordem permanente do consultor + roteador manda toda frase com "fatura" para o Opus (o Haiku lançaria o pagamento como gasto). |
| 4 | **Parcelas viram N linhas**, uma por mês, no mesmo ledger. | Todo resumo existente (mês, categoria, carteira, histórico, insights) funciona sem mudar. |

Fora desta versão: marcar fatura como paga, limite do cartão, regime de caixa,
importação automática de fatura (o consultor concilia o PDF na conversa),
estorno no cartão (registra-se como `income` em `conta` ou apaga-se a linha).

## 3. Modelo de dados

### 3.1 Tabela nova: `credit_card`

| coluna | tipo | regra |
|---|---|---|
| `id` | UUID PK | |
| `name` | str ≤ 40 | único após fold (case/acento); é o que o cliente diz: "Nubank" |
| `closing_day` | int 1–31 | dia de fechamento; num mês mais curto usa o último dia |
| `due_day` | int 1–31 | dia de vencimento; mesma regra de clamp |
| `is_default` | bool | **exatamente um** cartão padrão enquanto houver cartões; o primeiro criado vira padrão; marcar outro desmarca o anterior |
| `created_at` | datetime UTC | |

Não há soft-delete: `DELETE` só é aceito se nenhum lançamento referencia o
cartão (409 caso contrário).

### 3.2 `cashflow_entry` — quatro colunas novas

| coluna | tipo | regra |
|---|---|---|
| `card_id` | UUID FK `credit_card.id`, nulo, index | nulo = pix/débito/dinheiro/benefício |
| `installment_no` | int nulo | 1-based; nulo em compra à vista |
| `installment_count` | int nulo | total de parcelas; nulo em compra à vista |
| `installment_group` | UUID nulo, index | mesmo valor em todas as parcelas de uma compra |

Registrar em `_ADDED_COLUMNS["cashflow_entry"]` com DDL SQLite. O tipo de
`card_id`/`installment_group` no DDL **tem que casar com o que o SQLModel usa
para UUID no SQLite** (GUID → `CHAR(32)`); `card_id` leva
`REFERENCES credit_card(id)` e default NULL (única forma que o SQLite aceita
em `ALTER TABLE ADD COLUMN` com FK ligada). `init_db` roda `create_all` antes
de `_ensure_sqlite_columns`, então a tabela referenciada já existe.

**Invariantes (validadas no service, 422 na API):**

- `card_id` só com `kind = expense` **e** `wallet = conta`.
- `installment_count > 1` exige `card_id`.
- `installments` aceito de 1 a 48.

`wallet` **não muda**: compra no cartão continua `conta`, porque o dinheiro
sai da conta no vencimento. A regra "sobra investível = carteira `conta`" do
consultor continua correta sem retoque.

## 4. Serviços

### 4.1 `app/services/card_service.py` (novo)

- `list_cards`, `create_card`, `update_card`, `delete_card` — CRUD com a regra
  do único padrão: `create_card` do primeiro cartão força `is_default=True`;
  `is_default=True` em create/update desmarca o padrão anterior;
  `is_default=False` no cartão que É o padrão → `CardRuleError` (422, "marque
  outro cartão como padrão"); `delete_card` do padrão (permitido só sem
  lançamentos) promove o cartão restante mais antigo.
- `resolve_card(session, raw, *, kind, wallet) -> CreditCard | None`. Semântica
  do campo `card` da API (string livre, fold de case/acento):
  - **ausente/`None` → automático**: cartão padrão se `kind = expense` e
    `wallet = conta` e existir um padrão; senão nenhum.
  - `none`, `nenhum`, `pix`, `debito`, `dinheiro`, `conta` → **sem cartão**
    (pagamento explícito fora do cartão).
  - qualquer outro texto → nome de cartão cadastrado; desconhecido → erro
    `UnknownCardError` (422). Não cai no padrão em silêncio: um nome errado
    tem que voltar para o consultor perguntar/cadastrar.
  - cartão resolvido com `kind = income` ou `wallet ≠ conta` → `CardRuleError`
    (422).
- `invoices(card, *, today, months) -> list[Invoice]`: as `months` faturas
  que terminam na **aberta** (mais antiga primeiro). Uma fatura é identificada
  pela data de fechamento:
  - `closes_on(y, m) = date(y, m, min(closing_day, dias_do_mês))`
  - `period_start = closes_on(mês anterior) + 1 dia` · `period_end = closes_on`
  - `due_on` = primeira data com `day = min(due_day, dias_do_mês)` **estritamente
    depois** de `closes_on` (mesmo mês se `due_day > closing_day`, senão o
    seguinte; vira o ano quando preciso)
  - `status`: `open` se `today ≤ closes_on`; `closed` se
    `closes_on < today ≤ due_on`; `past` depois de `due_on` (sem controle de
    pagamento, "vencida" mentiria)
  - `total_brl` e `entries` = soma/contagem de `cashflow_entry` com
    `card_id = card.id` e `period_start ≤ occurred_on ≤ period_end`
  - a fatura **aberta** é a de menor `closes_on ≥ today`
- `card_summaries(session, today)`: por cartão, `open_invoice` (sempre
  existe, total 0 quando vazia) e `last_closed_invoice` (a fatura
  imediatamente anterior à aberta; `None` quando ela não tem lançamentos). É
  o que as telas consomem em uma chamada.
- **Faturas nunca são persistidas**: são calculadas a cada leitura a partir
  do cartão e dos lançamentos. Mudar `closing_day`/`due_day` no PATCH
  reagrupa o histórico inteiro na hora, sem migração.

### 4.2 `cashflow_service.py` — mudanças

- `add_entry(session, data)` passa a:
  1. resolver o cartão (`card_service.resolve_card`);
  2. validar invariantes (§3.2);
  3. expandir parcelas quando `installments > 1`: `amount_brl` do payload é o
     **TOTAL** da compra; cada parcela recebe `total / n` truncado em centavos
     e o resto vai para a parcela 1 (100 em 3x → 33,34 · 33,33 · 33,33);
     parcela k tem `occurred_on = data_da_compra + (k−1) meses`, dia
     clampado ao fim do mês **a partir da data original** (31/jan → 28/fev →
     31/mar, nunca 28/mar); todas compartilham `installment_group`,
     `installment_count = n`, `installment_no = k`, e os mesmos descrição,
     categoria, cartão, carteira e origem;
  4. deduplicar **antes** de gravar, comparando a parcela 1 (todos os campos,
     inclusive `card_id`, `installment_no` e `installment_count`, **exceto**
     `installment_group`, que é novo a cada chamada) na janela de 120 s:
     repetição do mesmo POST devolve a parcela 1 existente e não recria o
     grupo;
  5. devolver a parcela 1 (ou a linha única). A resposta do POST continua
     sendo **um** `CashflowRead`; `installment_count` avisa que há mais.
- `delete_group(session, group_id) -> int`: apaga todas as parcelas; 404 se
  nenhuma. `delete_entry` continua apagando uma linha só (parcela avulsa
  estornada é caso legítimo).
- `list_entries` ganha filtro `card_id`.
- `month_summary` ganha `card_expense_brl` (gastos do mês com `card_id`
  preenchido). Nada mais muda nos resumos.
- `_WALLET_ALIASES`: **remover** `cartao` e `credito` do mapa. Eles nunca
  foram carteira; com o cartão modelado, "cartao" chegando em `wallet` deve
  degradar para `conta` pelo caminho de desconhecido (com o warning), não pelo
  alias — assim um caller antigo que mande `wallet: "cartao"` fica visível no
  log durante a transição.

### 4.3 Insight novo: aviso de fechamento (`insight_service`)

Regra 3, determinística, **fora do orçamento semanal de pushes** (é conta a
pagar, não insight): no dia seguinte ao fechamento (`today == closes_on + 1`),
para cada cartão, envia via `notification_center.notify(kind=LEDGER,
url="/extrato")`:

> 💳 Fatura do Nubank fechou: R$ 3.412,90 · vence 03/10. 27 lançamentos.

Dedup em `storage/insights_state.json`: `"card_closing_fired": {"<card_id>":
"<closes_on ISO>"}`, podado para o último valor por cartão. Fatura fechada com
zero lançamentos **não** avisa (nada a pagar). Dispara mesmo no dia 1–4 do mês
(o `_MIN_ELAPSED_DAYS` é das regras 1–2). Roda pelo timer diário já existente
(`investimentos-insights`, 09:07) — nenhum timer novo.

## 5. API

### 5.1 `/api/cards` (router novo `app/routers/cards.py`)

| método | rota | corpo / query | resposta |
|---|---|---|---|
| GET | `/api/cards` | — | `list[CardRead]` com `open_invoice` e `last_closed_invoice` embutidos |
| POST | `/api/cards` | `CardCreate {name, closing_day, due_day, is_default=false}` | 201 `CardRead`; 409 nome repetido |
| PATCH | `/api/cards/{id}` | `CardUpdate` (todos opcionais) | `CardRead` |
| DELETE | `/api/cards/{id}` | — | `CardRead`; 409 se há lançamentos no cartão |
| GET | `/api/cards/{id}/invoices?months=6` | `months` 1–24 | `list[InvoiceRead]` (mais antiga primeiro, termina na aberta) |

`CardRead {id, name, closing_day, due_day, is_default, created_at,
open_invoice: InvoiceRead, last_closed_invoice: InvoiceRead | null}`.

`InvoiceRead {card_id, period_start, period_end, closes_on, due_on, status,
total_brl, entries}`.

### 5.2 `/api/cashflow` — mudanças

- `CashflowCreate` ganha `card: str | None = None` (semântica de §4.1) e
  `installments: int = 1` (1–48).
- `CashflowRead` ganha `card_id`, `card_name` (resolvido no router com um
  dicionário id→nome, uma query — sem N+1), `installment_no`,
  `installment_count`, `installment_group`.
- `GET /api/cashflow` aceita `card_id=<uuid>`.
- `DELETE /api/cashflow/groups/{group_id}` → `{"deleted": n}`; 404 se zero.
  **Declarar antes de** `DELETE /{entry_id}`: a rota por UUID rejeitaria
  "groups" com 422 se viesse primeiro.
- `CashflowSummary` ganha `card_expense_brl`.
- Erros do service (`UnknownCardError`, `CardRuleError`) → 422 com mensagem
  em pt-BR.

## 6. Motor de IA

### 6.1 Ordens permanentes do consultor (`chat_service`)

Acrescentar/alterar, mantendo o tom e o formato atuais:

- **Meio de pagamento**: "O cliente passa tudo no cartão. Gasto em `conta`
  sem meio explícito → omita `card` (a API aplica o cartão padrão). Pix,
  débito, dinheiro → `"card": "none"`. Outro cartão pelo nome →
  `"card": "<nome>"`. VR/VA nunca levam cartão."
- **Parcelas**: "'em 10x', '10 vezes', 'parcelei em 10' → `installments: 10`
  e `amount_brl` = TOTAL (10x de 200 → 2000). A API cria uma linha por mês."
- **Pagamento de fatura NÃO é gasto**: "'paguei a fatura' → não registre
  nada. Responda com a fatura fechada (`GET /api/cards`) e confira se o valor
  que ele pagou bate com `total_brl`. Diferença = compra que faltou
  registrar: pergunte o que foi e lance com a data da compra."
- **Fatura em PDF/CSV** (substitui a linha atual "Extrato/fatura → resuma e
  registre"): "Concilie linha a linha com
  `GET /api/cashflow?card_id=&month=` no período da fatura. Lance SÓ o que
  falta. Linha parcelada ('TV 03/10') → lance a compra inteira retroativa:
  `amount_brl` = parcela × n, `installments` = n, `occurred_on` = data da
  compra original (data da parcela na fatura menos k−1 meses); a API gera as
  parcelas passadas e futuras. Antes, confira que as parcelas não existem."
- **Cadastro pelo chat**: "'meu Nubank fecha dia 25 e vence dia 3' →
  `POST /api/cards`. Se não houver cartão cadastrado e o cliente registrar um
  gasto, registre o gasto (vai sem cartão) e pergunte UMA vez: qual cartão,
  fecha e vence que dia."
- **Resumo do mês**: incluir fatura aberta (total, fecha em, vence em) e a
  fechada aguardando pagamento.
- **API local**: documentar `card`, `installments`, `GET /api/cards`,
  `GET /api/cards/{id}/invoices`, `DELETE /api/cashflow/groups/{id}`.
- **MEMORY.md**: nota "Cartões ficam em `GET /api/cards`, não aqui". A tabela
  de gastos fixos deixa de sugerir "cartão" como exemplo de valor variável
  (a fatura não é gasto).

### 6.2 Classificador (`classifier_service`)

O JSON de saída ganha `"card": "auto|none|<nome>"` e `"installments": 1`.
Regras no prompt: padrão `auto`; pix/débito/dinheiro → `none`; nome de cartão
citado → o nome; "10x", "em 10 vezes", "parcelado em 10" → `installments: 10`
e `amount_brl` = total. No parse: `card` "auto"/ausente → `None` no
`CashflowCreate`; `installments` fora de 1–48 → 1 com warning. A API
`/classify` continua devolvendo rascunho, sem gravar.

### 6.3 Roteador (`model_router`)

`fatura` entra em `_ASKS_RE` **e** em `_ADVICE_RE`: qualquer mensagem com a
palavra sai do caminho rápido e do `lookup` e vai para o Opus. Motivo: "paguei
a fatura 3200" tem verbo no passado + valor e hoje cairia no Haiku, que
lançaria um gasto de R$ 3.200 fantasma. Frases de compra no cartão continuam
rápidas: "gastei 42 no cartão", "comprei a tv em 10x de 200" → fast.
("parcelei …" já vai para o Opus por `parcel\w*`; mantém.)

## 7. Frontend

### 7.1 `lib/api.ts`

Tipos `CreditCard`, `CardInvoice`, `CardCreate`; `CashflowEntry` +
`card_id`, `card_name`, `installment_no`, `installment_count`,
`installment_group`; `CashflowCreate` + `card?`, `installments?`;
`CashflowSummary.card_expense_brl`. Funções `fetchCards`, `createCard`,
`updateCard`, `deleteCard`, `deleteCashflowGroup`.

### 7.2 `/extrato`

- Bloco **Cartão** logo após "Saldo do mês", só quando existe cartão. Por
  cartão: fatura aberta (total grande, "fecha em dd/mm · N dias", "vence
  dd/mm") e, se houver, a última fechada ("Fatura fechada · R$ X · vence
  dd/mm"; se `past`, em tom apagado "última fatura R$ X, venceu dd/mm"). Sem
  cartão: uma linha "Cadastre seu cartão em Ajustes para acompanhar a fatura"
  com link.
- Linha secundária do lançamento: `categoria · Nubank · 3/10` (cartão e
  parcela quando existirem; VR/VA como hoje).
- Linha expandida: "Excluir" (a linha) e, se for parcela, "Excluir compra
  (10 parcelas)" chamando `deleteCashflowGroup`.
- Sob os trilhos Entrou/Saiu: "no cartão R$ X" (`card_expense_brl`) quando > 0.

### 7.3 `/configuracoes`

Seção **Cartões** acima de "Variáveis de ambiente": lista (nome · fecha dia
N · vence dia M · selo "padrão"), formulário inline de cadastro (nome, dia de
fechamento, dia de vencimento; controles ≥16px, alvos ≥44px), ação "tornar
padrão" e "remover" (mensagem clara no 409). Estado local simples, sem
biblioteca de formulário.

### 7.4 `/` (visão geral)

No card "O mês", uma linha compacta abaixo dos trilhos: "No cartão R$ X ·
fatura vence dd/mm" (usa `fetchCards`; some quando não há cartão). Nada mais
muda na tela.

## 8. Migração e operação

- Desktop: `init_db` cria `credit_card` e adiciona as 4 colunas no boot.
- Pi: o deploy normal (`rsync` + restart) faz o mesmo no primeiro boot; o
  banco não é sobrescrito. Sem passo manual.
- Nenhum timer, unit ou variável de ambiente nova.

## 9. Testes

Backend (pytest, TDD):

- `test_card_service.py`: janelas de fatura (fecha 25/vence 3; fecha 31 em
  fevereiro; `due_day < closing_day` → mês seguinte; virada de ano), status
  por data, único padrão, `resolve_card` (auto/none/nome/desconhecido/VR/
  income), delete com 409.
- `test_cashflow_service.py`: expansão de parcelas (centavos, datas clampadas
  a partir da original), dedup de POST repetido não duplica grupo,
  `delete_group`, cartão automático quando há padrão, `none` explícito,
  cartão + VR rejeitado, `card_expense_brl`, `installments` sem cartão
  rejeitado.
- `test_cards_api.py`: CRUD, `invoices`, `groups` declarado antes de
  `/{entry_id}`, 422 com mensagem.
- `test_classifier_service.py`: `card`/`installments` no JSON e ausentes.
- `test_model_router.py`: "paguei a fatura 3200" → deep; "gastei 42 no
  cartão" → fast; "comprei tv em 10x de 200 no cartão" → fast; "quanto tá
  minha fatura?" → deep.
- `test_insight_service.py`: aviso no dia seguinte ao fechamento, uma vez,
  fora do orçamento; silêncio no próprio dia e com fatura vazia.
- `test_database.py`: as 4 colunas entram por `ALTER TABLE` num banco antigo
  com FK ligada.

Frontend: `pnpm lint && pnpm type-check && pnpm build`. Validação visual no
iPhone via Tailscale depois do deploy.

## 10. Documentação a atualizar

`docs/03-dominio.md` (tabela nova, colunas, invariantes, regime),
`docs/06-api.md` (`/api/cards`, mudanças em `/api/cashflow`),
`docs/07-frontend.md` (extrato, ajustes, visão geral), `docs/04-motor-ia.md`
(regra "fatura → opus", ordens do consultor), `docs/12-decisoes.md` (D39:
competência + cartão padrão + pagamento de fatura não é gasto + `cartao`
removido dos aliases de carteira), `docs/13-estado-atual.md` (entrada da
data), `CLAUDE.md` (dois bullets no bloco do ledger pessoal).
