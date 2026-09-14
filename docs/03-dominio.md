# 03 · Domínio, dados e regras de negócio

## As 10 tabelas

Todas em `app/models/`, SQLModel, PK `UUID`, timestamps em UTC.

```
Contribution ──1:N──▶ ContributionPrompt        (aporte → 5 prompts + respostas)
     │
     └────1:N──▶ Order ──executa──▶ Asset ──vende──▶ Trade
                                      │                 ▲
                                      └── é fotografado em ──▶ PortfolioSnapshot
Report          (weekly · maturity · monthly)
CashflowEntry   (ledger pessoal: gasto/ganho)
CreditCard      (cartão de crédito: fechamento, vencimento, padrão)
Recurrence      (compromisso mensal: salário, aluguel, assinatura)
ChatMessage     (transcrição do consultor, telegram + web)
```

### `Asset` — um LOTE, não um ticker

**O conceito mais importante do domínio.** Cada linha é uma *compra*, com seu
próprio `entry_date`. Duas compras de PETR4 em datas diferentes são duas linhas,
maturam independentemente e são vendidas separadamente.

Campos além do óbvio (`ticker`, `asset_class`, `quantity`, `avg_price`,
`current_price`, `entry_date`):

- `thesis`, `target_price`, `stop_price` — contexto do comitê para **este lote**.
  Preenchidos ao executar uma `Order`. Alimentam a revisão semanal (a tese é
  reavaliada explicitamente: intacta / enfraquecida / quebrada) e os alertas de
  preço.

`AssetClass`: `fixed_income` · `stocks` · `crypto`.

### `Trade` — ledger imutável

Toda compra e toda venda vira uma linha, **para sempre**. Vender apaga o
`Asset`; o `Trade` permanece. É a base de:

- P&L realizado (`realized_pnl_brl`, `realized_pnl_pct`)
- track record injetado nos aportes (hit rate das vendas)
- apuração de IR
- neutralização de fluxo no benchmark (TWR)

`lot_entry_date` guarda a data de entrada do lote fechado (contabilidade por
lote).

### `Contribution` + `ContributionPrompt`

`Contribution` é um aporte: valor, snapshot macro e de carteira congelados na
criação, `final_summary` (o fechamento), `notes`.

Dois campos de resiliência:
- `claude_session_id` — a sessão encadeada do Claude, para retomar entre
  reinícios de processo.
- `run_attempts` — falhas automáticas consecutivas; ao bater `MAX_RUN_ATTEMPTS`
  (5) o auto-resume desiste e avisa no Telegram (evita loop pago infinito).

`ContributionPrompt` é uma reunião: `prompt_order`, `prompt_key`, `content`
(prompt renderizado), `response`, e telemetria (`cost_usd`, `duration_s`,
`num_turns`).

`ContributionStatus`: `pending` → `ready` → `in_progress` → `completed`.
Em falha volta para `ready` (retentável) e a causa é **anexada** em `notes`
(nunca sobrescreve o texto do usuário).

`PromptKey`: `macro` · `selection` · `equity_diligence` · `crypto_diligence` ·
`decision` · `research` (legado, aportes anteriores ao split de 2026-05-24).

### `Order` — a ponte recomendação → realidade

Gerada do bloco ```json {"orders": [...]}``` do fechamento. `pending` →
`executed` | `skipped`. Ao executar, cria o `Asset` **herdando tese/alvo/stop**
e grava `executed_quantity`, `executed_price`, `executed_asset_id`,
`executed_at`. É isso que permite medir "o comitê recomendou X, eu comprei Y a
que preço".

### `Report`

Saída das rodadas autônomas: `weekly` · `maturity` · `monthly`. Guarda
`content` (o texto que vai pro Telegram), `cost_usd`, `session_id`, snapshots e
`steps` (cada etapa encadeada, auditável).

### `PortfolioSnapshot`

Uma linha por dia (upsert, idempotente). Alimenta a curva de patrimônio e o
benchmark. `assets` guarda o detalhe por ativo em JSON para auditar o dia depois.

### `CashflowEntry` — ledger pessoal

Separado do `Trade` de propósito: trade é operação de carteira, isto é vida
(mercado, aluguel, salário). `kind` = `expense`|`income`; `category`
normalizada para minúsculas; `source` = `chat`|`bot`|`api`.

**Carteiras (`wallet`, 2026-08-06):** todo lançamento diz de qual pote o
dinheiro saiu/entrou — `conta` (banco/pix/cartão, padrão), `vr`
(vale-refeição) ou `va` (vale-alimentação). Vocabulário FECHADO, ao contrário
das categorias: `normalize_wallet` dobra apelidos ("Vale Refeição" → `vr`) e
degrada desconhecidos para `conta` (o comportamento pré-carteiras), nunca
inventa um quarto saldo. VR/VA são benefício que só compra comida — o
consultor é instruído a NUNCA somá-los como sobra investível; o resumo mensal
expõe `by_wallet[]` e `GET /api/cashflow/wallets` dá o saldo ACUMULADO de
benefício (crédito rola entre meses). No banco a coluna armazena o VALOR
minúsculo (`values_callable` no `SAEnum`) — diferente de `kind`/`source`, que
o SQLModel guarda pelo NOME — porque linhas antigas ganham o default `'conta'`
do `ALTER TABLE` e o ORM precisa ler esse texto cru de volta.

### `Recurrence` — compromisso mensal (2026-09-13)

Salário, aluguel, assinatura, financiamento. É **configuração, não
lançamento**: nada aqui escreve no ledger, e o fluxo de caixa
(`forecast_service`) recalcula a partir destas linhas a cada leitura — a mesma
escolha que já vale para fatura. Materializar as parcelas futuras em
`cashflow_entry` duplicaria o gasto no dia em que ele acontece de verdade.

Campos: `kind`, `amount_brl`, `category` (normalizada como no ledger),
`day_of_month` (1–31, mês curto cai no último dia), `wallet`, `card_id`,
`starts_on` (default: dia 1 do mês corrente), `ends_on` (NULL = indefinido —
preencher é o que faz o financiamento sumir do fluxo) e `active`.

`card` em branco significa **fora do cartão**, ao contrário do lançamento
avulso: compromisso mensal costuma ser boleto ou pix, e o consultor pode ser
explícito quando for no cartão.

**Deduplicação:** um lançamento idêntico em todos os campos (carteira
inclusive) dentro de 120s é tratado como repetição do mesmo POST e devolve a
entrada existente (`cashflow_service._recent_duplicate`). Motivo: o consultor
às vezes posta, não lê a resposta, e posta de novo — o que dobrava o gasto
silenciosamente.

**Cartão de crédito (`card_id`, 2026-09-12):** compra no cartão é gasto em
`conta` (o dinheiro sai da conta no vencimento) com `card_id` apontando para
um `CreditCard`. **Regime de competência**: conta no mês da compra
(`occurred_on`); pagar a fatura NUNCA vira lançamento. Regra do padrão em
`card_service.resolve_card`: `card` ausente → cartão padrão se `kind=expense`
e `wallet=conta`; `none`/`pix`/`debito`/`dinheiro` → sem cartão; nome
desconhecido → 422 (nunca cai no padrão em silêncio). Cartão em `income` ou
em VR/VA → 422. Os apelidos `cartao`/`credito` saíram de `_WALLET_ALIASES`:
cartão não é carteira.

**Parcelas:** `installments` (1–48) expande em N linhas, uma por mês
(`_add_months` clampa o dia a partir da data ORIGINAL: 31/jan → 28/fev →
31/mar), `amount_brl` do payload é o TOTAL, centavos sobrando na parcela 1
(`_split_installments`). As N linhas compartilham `installment_group` e
levam `installment_no`/`installment_count`; `delete_group` apaga a compra
inteira. Parcelamento exige cartão.

### `CreditCard` — cartão de crédito

`name` (único após fold), `closing_day`, `due_day` (1–31, clampados ao fim do
mês curto), `is_default` (exatamente um enquanto houver cartões: o primeiro
vira padrão, promover outro rebaixa o anterior, remover o padrão promove o
mais antigo). **Faturas nunca são persistidas**: `card_service.invoice_window`
calcula `(fechamento anterior, fechamento]`, `due_on` = primeira ocorrência
de `due_day` estritamente após o fechamento, status `open` (`hoje ≤
fechamento`) · `closed` (até o vencimento) · `past`. Sem controle de
pagamento. `DELETE` só sem lançamentos (409).

### `ChatMessage` — transcrição compartilhada

Toda mensagem, dos dois lados e das **duas portas** (Telegram e site). Guarda
`channel`, `status` (`queued`/`running`/`done`/`failed`), `model` e `tier`
escolhidos pelo roteador, custo e duração.

A tabela é **também a fila** (D41): a linha do assistente pendente É o job, com
`prompt` (o texto que vai ao modelo, distinto do `content` que o humano lê),
`attempts`, `run_after` e `retry_kind`. Por estar no banco, uma mensagem barrada
pelo limite de uso atravessa restart e é respondida quando o crédito volta.

> **Regra crítica:** todo caller entra por `chat_service.enqueue(text, channel)`
> (site: enfileira e volta na hora) ou `chat_service.converse(text, channel)`
> (bot: síncrono, porque precisa devolver o texto na resposta do Telegram) —
> **nunca** `run_chat_turn` direto, que não persiste nada.
> Rotacionar a sessão do Claude não apaga esta tabela. O reset ("nova
> sessão") também não: ele grava um corte em `display_state.json` e
> `history()` só devolve o que veio depois — a tela recomeça em branco
> com o banco intacto (custo e tiers do relatório mensal dependem dele).

## Regras de negócio invioláveis

### 1. Trava de venda: por LOTE **e por CLASSE**

```python
# portfolio_service.holding_lock_days()  ← fonte única da regra
fixed_income → 0                       (nunca trava)
crypto       → MIN_HOLDING_DAYS_CRYPTO (7)
stocks       → MIN_HOLDING_DAYS        (30)

# portfolio_service.sell_lock_days_left()
max(0, holding_lock_days(classe) - (hoje - entry_date).days)
```

Os 30 dias das ações são **exigência de compliance do cliente** (ele trabalha no
mercado financeiro e a regra alcança valores mobiliários), não disciplina —
não encurte. Cripto não é valor mobiliário e é o bolso que existe para fazer
dinheiro: 7 dias, o suficiente para a revisão semanal ver o lote uma vez antes
de ele destravar (D36).

Aplicada **no service** (`sell_asset` levanta `SellLockedError` → API 409), não
em cada caller. O bot pede confirmação em dois passos antes de vender. Nenhuma
outra camada recalcula a regra: `AssetRead` já traz `lock_days_total` /
`lock_days_left` e o `PortfolioSummary` traz `holding_lock_days` por classe.

**CDB é dry powder:** liquidez diária, vendável a qualquer hora, excluído de
`pending_maturities`. A revisão semanal pode recomendar vender CDB para comprar
uma oportunidade — a nova compra entra na trava da sua classe.

### 2. Marcação a mercado

Sem isso o sistema é cego: `current_price` nasce igual a `avg_price` e o P&L
ficaria 0% para sempre.

| Classe | Fonte |
|---|---|
| Ações | Yahoo Finance, com fallback de sufixo `.SA` |
| Crypto | CoinGecko (id resolvido por busca quando o ticker não é id) |
| CDB | CDI diário acumulado (série BCB **12**) desde `entry_date` × `CDB_PCT_CDI` |

Roda via timer (a cada 6h), `POST /api/portfolio/refresh`, `/atualizar` no bot,
e antes de todo snapshot/revisão.

⚠️ Série BCB **4389** é o CDI anualizado (% a.a.). A **4391** é mensal e já
injetou um ~0,75 errado nos prompts. Não troque.

### 3. Alocação e desvio

`get_portfolio_summary` devolve alocação atual (%), alvo (do `.env`) e desvio
(atual − alvo). Alvos precisam somar 1.0 ± 0.01 ou o `Settings` explode no boot.

### 4. Benchmark = TWR, não valor bruto

`benchmark_service` constrói retorno ponderado no tempo a partir dos snapshots,
**neutralizando fluxos** com o ledger `Trade`: compra injeta dinheiro no pool,
venda tira (o sistema não guarda caixa). Sem isso, todo aporte pareceria
"performance".

`r_t = (V_t − F_t − V_{t−1}) / (V_{t−1} + F_t)`, fluxo assumido no início do dia.
Benchmarks (CDI composto do BCB, IBOV do Yahoo, BTC/BRL do CoinGecko) são
normalizados a 100 na primeira data comum e forward-filled nos dias de snapshot.

### 5. IR (simplificado — não substitui contador)

| Classe | Regra |
|---|---|
| Ações B3 | vendas do mês ≤ R$ 20.000 → isento; acima, 15% sobre o ganho líquido, compensando prejuízo acumulado |
| Crypto | vendas do mês ≤ R$ 35.000 → isento; acima, 15% com a mesma compensação |
| CDB | IR retido na fonte (tabela regressiva) — só informativo, alíquota estimada pelo prazo do lote |

DARF mínima de R$ 10 (valores menores acumulam para o mês seguinte).
**Não cobre:** day-trade, JCP/dividendos, corretagem, eventos societários.

## Migrações de schema (leia antes de adicionar coluna)

**Não há Alembic.** `SQLModel.metadata.create_all()` cria tabelas novas mas
**não adiciona coluna em tabela existente**. A solução é
`app/core/database.py::_ADDED_COLUMNS`:

```python
_ADDED_COLUMNS = {
    "contribution": {"claude_session_id": "TEXT", "run_attempts": "INTEGER NOT NULL DEFAULT 0"},
    "contribution_prompt": {"cost_usd": "REAL", "duration_s": "REAL", "num_turns": "INTEGER"},
    "asset": {"thesis": "TEXT", "target_price": "NUMERIC", "stop_price": "NUMERIC"},
    "cashflow_entry": {"wallet": "TEXT NOT NULL DEFAULT 'conta'", "card_id": "CHAR(32) REFERENCES credit_card(id)", ...},
}
```

UUID no SQLite é `CHAR(32)`; coluna com `REFERENCES` só entra por `ALTER TABLE`
com default NULL (e `create_all` já criou a tabela pai antes).

**Ao adicionar um campo a uma tabela existente:** declare no modelo **e**
registre aqui com o DDL SQLite. `_ensure_sqlite_columns()` roda no boot, checa
`PRAGMA table_info` e faz `ALTER TABLE ADD COLUMN` no que faltar.
Coberto por `tests/test_database.py`.

## PRAGMAs do SQLite (`core/database.py`)

Aplicados por conexão, porque API + bot + 8 crons escrevem no mesmo arquivo:

```sql
PRAGMA journal_mode=WAL      -- leitor concorrente durante escrita
PRAGMA synchronous=NORMAL    -- par seguro recomendado com WAL
PRAGMA busy_timeout=5000     -- espera em vez de "database is locked"
PRAGMA foreign_keys=ON       -- FK de verdade
```

⚠️ Com `foreign_keys=ON` e **sem** relacionamentos ORM declarados, o SQLAlchemy
não ordena os deletes sozinho. Ao apagar um pai, apague os filhos primeiro com
`session.flush()` explícito — é o que `delete_contribution` faz.
