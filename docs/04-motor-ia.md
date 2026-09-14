# 04 · Motor de IA

> Arquivo central: `app/services/analysis_runner.py` (1494 linhas). Se algo de
> IA quebrou, começa aqui.

## O princípio

O sistema **não usa a API da Anthropic**. Ele abre o binário `claude` (Claude
Code CLI) como subprocess:

```bash
claude -p --output-format json --dangerously-skip-permissions \
       --model opus --effort max \
       --add-dir $HOME \
       --mcp-config <workspace>/.mcp.json --strict-mcp-config \
       [--resume <session_id>]
# prompt entra por stdin
```

A saída é um JSON com `result`, `session_id`, `total_cost_usd`, `num_turns`,
`is_error`. A **primeira** etapa roda fresh e o `session_id` é capturado; as
seguintes usam `--resume <id>` — é assim que as 5 reuniões herdam contexto uma
da outra, exatamente como colar os prompts em sequência à mão.

Consequência: o agente é um Claude Code completo. Tem Bash, WebSearch, WebFetch,
MCPs e acesso ao filesystem. O "prompt" não é só texto — é um **workspace em
disco** com `CLAUDE.md`, `MEMORY.md`, ferramentas e notas.

## Os quatro workspaces

| Workspace | Quem usa | Modelo | Tem `.mcp.json`? |
|---|---|---|---|
| `storage/agent_workspace/` | comitê (aporte, semanal, maturidade) | `opus` / effort `max` | sim, baseline completo |
| `storage/chat_workspace/` | consultor (chat) | roteado: haiku/sonnet/opus | sim, **perfil enxuto** (`profile="chat"`: só dados financeiros + fetch + memory) |
| `storage/classifier_workspace/` | classificador de gasto | `haiku` / `low` | **não, de propósito** |

> A **ausência** do `.mcp.json` é o que mantém os dois últimos rápidos (~5s):
> nenhum servidor MCP boota. Não "conserte" isso adicionando config.

### Anatomia do `agent_workspace/`

| Arquivo | Quem escreve | Sobrevive ao ciclo? |
|---|---|---|
| `CLAUDE.md` | **o código**, a cada run (`_STANDING_ORDERS`) | reescrito sempre — edite no Python, não no arquivo |
| `MEMORY.md` | **o agente** | sim (é a memória dele entre ciclos) |
| `.mcp.json` | **o código**, a cada run | regenerado = baseline ∪ `.mcp.agent.json` |
| `.mcp.agent.json` | **o agente** | sim, **nunca sobrescrito** |
| `tools/` | o agente | sim (workspace é repo git) |
| `notes/` | o agente | sim (rascunhos por round; não use `/tmp`) |
| `out/<contribution_id>/etapa_NN.json` | o agente | sim — fonte canônica entre etapas se o contexto truncar |
| `memory/graph.json` | MCP `memory` | sim |

O `chat_workspace/` é análogo, mais `session.json` (session_id + contagem de
turnos) e `inbox/` (fotos e arquivos recebidos, ≤20 MB).

## MCPs — três tiers

Construídos em `_baseline_mcp_servers()` e mesclados em `_effective_mcp_config()`
(o agente vence em conflito de nome). Sempre com `--strict-mcp-config`, então
**só** esse conjunto carrega — Gmail/Calendar/Drive do usuário ficam de fora de
propósito (o agente é autônomo e não deve agir neles).

**Todos os pacotes de terceiros são PINADOS** (`_MCP_PINS`: versão exata
npm/PyPI, commit sha do git — D21). Eles rodam com permissão total na máquina;
um `@latest` comprometido seria execução arbitrária no Pi. Para atualizar um
servidor, mude o pin deliberadamente e olhe o diff do pacote.

**Tier 1 — runtime e raciocínio (6, sempre no comitê):** `sequential-thinking`,
`filesystem` ($HOME), `fetch`, `context7`, `playwright`, `memory`. Datas/fusos e
git saem pelo Bash (`date`, `git`) — os servidores dedicados `time` e `git`
foram removidos por redundância (2 processos uvx a menos por run).

**Perfis por workload (D23)**: `_baseline_mcp_servers(workspace, profile=)`.
O comitê carrega tudo; o chat (`profile="chat"`) só `fetch` + `memory` + os
servidores de dados (coingecko, yahoo-finance, defillama, exa + key-gated).
Cada turno de chat boota a lista inteira como subprocessos no Pi — e o turno
mais frequente ("gastei X no mercado") não precisa de navegador nem
filesystem. O `.mcp.agent.json` do chat continua mesclando por cima, então o
agente readiciona o que sentir falta.

**Tier 2 — dados financeiros sem chave (4, sempre):**
- `coingecko` (HTTP remoto) — preços/market cap de qualquer cripto, fonte
  canônica de identidade (CoinGecko-id)
- `yahoo-finance` (uvx do GitHub) — ações B3 com sufixo `.SA`, fundamentos,
  demonstrações, opções
- `defillama` — TVL, yields/APY, receita de protocolos
- `exa` (HTTP remoto) — busca semântica em fontes de qualidade

**Tier 3 — premium key-gated (5, só se a chave existir no `.env`):**
`glassnode` (on-chain), `coinglass` (derivativos), `messari` (tokenomics),
`firecrawl` (scraping estruturado), `tavily` (research com citação).
Definidos em `_KEY_GATED_MCP_SERVERS`; a chave chega ao run via
`_agent_subprocess_env()` e o JSON usa `${VAR}` (segredo não vai para o disco).

### Auto-provisionamento

O agente pode adicionar **qualquer** MCP novo escrevendo em `.mcp.agent.json`.
Ele é mesclado ao baseline a cada run e carrega no **próximo** ciclo (MCPs
sobem no início do processo). Para uso imediato, o agente chama a CLI via Bash.

### ⚠️ Playwright no Pi

`@playwright/mcp` aponta para o Google Chrome, que **não tem build ARM64 para
Linux**. `_playwright_mcp_args()` detecta a ausência de `/opt/google/chrome/chrome`
e cai para o Chromium do sistema com `--headless`. **Não simplifique de volta.**

### Higiene de ambiente

`_agent_subprocess_env()` herda o env do pai **menos** uma deny-list:
prefixos `AWS_`, `GCP_`, `AZURE_`, `OPENAI_`, `GOOGLE_API` e exatos
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GMAIL_APP_PASSWORD`, `GITHUB_TOKEN`,
`GH_TOKEN`. O agente tem acesso total à máquina — não entregue a identidade do
bot nem credencial de nuvem alheia a ele.

## `run_chain()` — o encadeador genérico

```python
run_chain(steps: list[tuple[titulo, prompt]], *, run_id, model, effort,
          step_timeout, persist=callback, on_event=callback,
          resume_session_id=None, on_session_id=callback,
          step_offset=0, total_steps=None, limit_backoff=None) -> RunSummary
```

- Etapa 1 fresh → captura `session_id` → etapas seguintes `--resume`.
- Algumas versões da CLI **rotacionam** o session id no resume; o código sempre
  adota o mais recente, senão o próximo resume miraria numa sessão morta.
- `persist(index, title, result)` é chamado ao fim de cada etapa → progresso
  durável e observável.
- `step_offset`/`total_steps` mantêm a numeração absoluta em retomadas (a UI
  mostra "etapa 4/6", não "1/3").
- Segura o **lock global** durante toda a corrente.

Usado por: aporte (5 reuniões + fechamento), revisão semanal (2 etapas),
maturidade (2 etapas).

## Resiliência — o que acontece quando falha

### Classificação de erro (`_run_claude_step`)

O stderr + `result` + `subtype` viram um blob minúsculo e são casados contra
listas de padrões:

| Classe | Padrões (exemplos) | Ação |
|---|---|---|
| `SessionNotFoundError` | "no conversation found", "session not found" | recomeça do zero (não retenta o resume) |
| `AnalysisError` (duro) | "prompt is too long", "context length", "invalid api key" | desiste — o prompt é que está errado |
| `LimitError` | "rate limit", "usage limit", "429", "resets at", "5-hour", "quota" | **espera e retoma** |
| `RetryableError` | qualquer falha desconhecida, timeout, saída vazia | 3 retries rápidos (20s, 60s, 120s) |

### Espera inteligente por limite

`_seconds_until_reset()` parseia "resets 8:20pm" da mensagem e espera **exatamente**
até a janela reabrir (+60s de folga, teto de 6h). Se anunciado às 23h que
"resets 1am", rola para o dia seguinte. Sem hora anunciada, backoff escalonado:
`60 → 300 → 900 → 1800 → 3600 → 3600 → 3600`.

**Contadores independentes** para limite × transiente: uma noite inteira de
espera por limite não pode consumir o orçamento de retry que um blip de rede
precisa depois.

### Retomada em três níveis

1. **Dentro do processo** — `_run_step_resilient` espera e retoma a MESMA etapa.
2. **Entre reinícios de processo** — `claude_session_id` está no banco e cada
   resposta é salva ao concluir. Re-rodar `run_analysis` retoma da 1ª etapa sem
   resposta, na MESMA sessão. Se a sessão sumiu, recomeça do zero **e limpa as
   respostas antigas** (`_clear_stale_responses`) — senão uma retomada futura
   contaria etapas que a nova sessão nunca viu.
3. **Automática, sem ninguém mandar** — `scripts/resume_pending.py` roda a cada
   15 min, acha análises incompletas (`pending_resumable_ids`) e retoma
   fail-fast (uma espera curta; tenta de novo no próximo pass). Avisa no
   Telegram. Desiste após `MAX_RUN_ATTEMPTS` (5) falhas consecutivas.

### Locks (arquivos em `storage/analysis_runs/`)

| Lock | Escopo | Por quê |
|---|---|---|
| `<contribution_id>.lock` | por aporte | a mesma análise nunca roda em dobro (CLI × API × bot × resume) |
| `_global_run.lock` | máquina inteira | **uma** execução pesada de Claude por vez — comitê, semanal e maturidade dividem a mesma janela de uso |
| `_chat_turn.lock` | chat | serializa turnos. **Não usa o lock global** — chat funciona mesmo com o comitê rodando |

Todo teste de posse passa por `_lock_is_active` (pid + starttime). Nunca conclua
"está ocupado" só porque o arquivo existe: um kill duro deixa lock órfão, e foi
exatamente isso que travou o chat do site por tempo indeterminado (armadilha A25
em `12-decisoes.md`). `is_run_active()` e `chat_service.is_busy()` são os dois
lugares que respondem essa pergunta — ambos validam liveness.

Implementação: criação atômica com `O_CREAT|O_EXCL`, payload com `pid` +
`pid_identity` (starttime de `/proc/<pid>/stat`) + `started_at`. O lock só está
"vivo" se o pid existe **e** é o mesmo processo — assim uma espera legítima de
horas segura o lock, mas um pid reciclado após reboot não consegue fingir posse.
**Não há reclaim por idade.**

`is_run_active()` deixa a API distinguir "rodando de verdade" (409) de um
`IN_PROGRESS` órfão deixado por um crash (re-run permitido).

### Transcripts

Todo `stdout`/`stderr` bruto de cada invocação vai para
`storage/analysis_runs/transcripts/<tag>_<timestamp>.stdout.json`. É o flight
recorder: um run de várias horas que morre deixava nada para trás. Best-effort,
nunca derruba o run.

### Matar a árvore de processos

`claude` gera filhos npx/uvx (os MCPs). Matar só o pai deixa órfão comendo RAM
para sempre. Por isso `start_new_session=True` + `os.killpg(proc.pid, SIGKILL)`
em `_kill_process_tree`.

## Contexto injetado no aporte

Antes da Reunião nº 1, quatro blocos são prefixados ao primeiro prompt:

1. **Preâmbulo** (`_build_preamble`) — valor do aporte, data LOCAL, mandato,
   trava por lote, ordem de ler/atualizar `MEMORY.md`, onde salvar os JSONs.
2. **Consulta à última revisão semanal** (`_latest_weekly_context`) — até 10000
   chars, cortado em fronteira de parágrafo. Generoso de propósito: no **modo
   delta** (abaixo) este bloco É a pesquisa macro que a Reunião nº 1 deixou de
   refazer, então truncá-lo custaria mais do que economiza.
3. **Track record** (`_track_record_context`) — últimas 12 vendas com P&L e hit
   rate. Sem isso o comitê é um oráculo sem memória de ter errado.
4. **Ordens pendentes** (`_pending_orders_context`, 2026-08-06) — a folha
   anterior ainda não executada, para o comitê não re-recomendar um nome já em
   aberto nem ignorar capital já comprometido.

As Reuniões nº 3 e nº 4 (DD por nome) rodam com **2× o timeout** das demais
(`step_timeouts` do `run_chain`).

### Modo delta da Reunião nº 1 (D37)

A Reunião nº 1 tem **dois templates**. O completo roda as 11 rodadas de macro do
zero e mediu **US$ 19,84** dos ~US$ 63 de um aporte. Quando existe uma revisão
semanal com até `MACRO_DELTA_MAX_AGE_DAYS` (7) dias, essa pesquisa já foi feita
pelo mesmo comitê e está colada no prompt como bloco de consulta — então
`prompt_generator` renderiza `01_macro_delta.j2`: precifica só **o que mudou**,
com orçamento explícito de ~8 buscas, e refaz a alocação tática.

Sem revisão semanal (ou com uma velha), cai no template completo — o comitê
nunca começa um aporte às cegas. `contribution_service` resolve a idade da
revisão (`review_service.last_weekly_age_days`) na hora de renderizar; o delta
emite **o mesmo contrato JSON** que as Reuniões 2-5 leem (`final_tactical_brl`,
`juros_e_cdb`, `setores_b3`, `digital_assets`, `top_of_mind`, `pre_mortem_gic`),
e há teste fixando isso. `MACRO_DELTA_ENABLED=false` volta ao template completo
sempre.

## Fechamento e bloco de ordens

Depois das 5 reuniões, roda `_SYNTHESIS_PROMPT`: um esqueleto **rígido** de
"onde investir e quanto" (entradas numeradas, totais por classe, soma que bate
±R$ 5), sem recap, sem próximos passos, sem disclaimer.

Depois de `---`, um bloco ```json {"orders": [...]}``` legível por máquina.
`order_service`:
- `parse_orders_block` — pega o **último** bloco json válido
- `_normalize_class` — tolerante: `equity_b3`, `fixed_income_cdb`,
  `crypto_stablecoin` etc. caem nas 3 classes por substring
- `_first(row, *sinônimos)` — modelos parafraseiam nomes de campo
- `strip_machine_block` — o cliente vê **só** a estrutura limpa; o bloco fica no
  banco para ingestão
- `ingest_contribution_orders` — idempotente (pula se o aporte já tem ordens),
  best-effort (linha malformada é logada e descartada, nunca falha o run)
- `summarize_block` — checagem determinística do bloco (linhas válidas, soma,
  desvio vs. aporte)

**Validador pós-run (D18, 2026-08-06)**: após a última etapa,
`_validate_and_correct_final` confere o bloco com `summarize_block`; bloco
ausente ou desvio > 2% dispara UM turno corretivo na MESMA sessão ("reemita o
fechamento com a soma batendo"); a correção só substitui a original se parsear
pelo menos tão bem. Após o ingest, linha descartada ou desvio residual vira
alerta no Telegram ("Checagem da folha de ordens: X/Y linhas…").

## Chat do consultor

`chat_service.py`. Uma sessão encadeada persistente por `session.json`,
rotacionada a cada `CHAT_MAX_TURNS` (40) turnos — o `MEMORY.md` carrega o
contexto durável através da rotação e, desde 2026-08-06 (D20), a sessão nova é
**semeada com os últimos ~10 turnos da transcrição** (`_transcript_tail`, lidos
de `chat_message`), então o assunto em andamento sobrevive à rotação de fato.
Desde o upgrade do consultor (D24), a rotação de uma conversa longa também
gera um **resumo estruturado** (`_rotation_summary`: haiku no workspace pelado
do roteador, 5 seções fixas, números copiados verbatim, best-effort) injetado
antes da cauda verbatim. A sessão renascida por `SessionNotFoundError` zera o
contador de turnos (A35) — antes herdava o da sessão morta e rotacionava de
novo na mensagem seguinte. `converse()` persiste `cost_usd`/`duration_s` na
`ChatMessage`, e `reconcile_orphan_turns()` (startup do backend) marca como
FAILED bolhas RUNNING órfãs de um restart.

- Turno fresh recebe instrução de **ler `./MEMORY.md` antes de responder**.
- Limite de uso → `ChatUnavailableError(kind="limit")`, e a mensagem **volta
  para a fila** com `run_after` na hora do reset: o consultor retoma sozinho
  quando o crédito volta (D41). Só `auth` (login expirado) não é retentado.
- `enqueue()` grava as duas pontas em `ChatMessage` e devolve na hora; quem
  roda é o worker da fila (um turno leva minutos, nenhum cliente HTTP segura
  isso). `converse()` é o caminho síncrono que o bot usa.
- Anexos: `save_attachment` → `inbox/`, nome saneado (`safe_filename`, ASCII,
  sem traversal), 20 MB de teto. `media_turn_text` monta o prompt que manda o
  consultor ler o arquivo e agir (cupom → registra gasto; extrato → resume e
  lança).

As **ordens permanentes do consultor** (`_CONSULTANT_ORDERS`, ~220 linhas) são o
coração comportamental dele e cobrem: registrar gasto/ganho via API, análise
"como estou indo?" com opinião, framework de **sourcing de liquidez** (caixa →
CDB → lote livre, contando isenção de IR), disparar aporte sozinho, gestão da
memória fixa, regra de recorrente ("lembrar não basta, tem que lançar"),
anti-duplicação, MCPs disponíveis, anti-manipulação e formato de resposta
(≤12 linhas, celular).

Ordens de cartão (2026-09-12): gasto da conta sem meio explícito vai sem
`card` (a API aplica o padrão); pix/débito/dinheiro → `"card": "none"`;
parcelas → `installments` + total; **pagamento de fatura NUNCA é lançado** —
o consultor lê `GET /api/cards` e concilia; fatura em PDF é conciliada linha a
linha contra `GET /api/cashflow?card_id=`. Cartões ficam no banco, não no
MEMORY.md.

## Roteador de modelo

`model_router.py`. Antes, todo turno era opus/high — correto para "devo trocar
CDB por PETR4?" e absurdo para "oi". **Três tiers, decididos por regra, sem
chamar modelo nenhum** (a triagem por LLM foi removida em D31: no Pi custava
5,6s de processo novo).

```
saudação (≤24 chars, regex)              → FAST    haiku/low
verbo de lançamento + valor              → FAST    (dígito OU por extenso;
                                                    SEM palavra de mercado)
consulta FACTUAL (≤160 chars):           → LOOKUP  sonnet/low
  frase de recuperação (quanto tenho,
  qual o preço, ordens pendentes…)
  E nenhuma palavra de julgamento
tudo o mais                              → DEEP    opus/high
CHAT_ROUTER_ENABLED=false                → DEEP sempre
```

O tier LOOKUP (D37) existe porque ler um número que o app já tem não é
consultoria: o histórico media **US$ 1,67 por turno** em opus, o preço de uma
opinião de investimento, não o de um saldo. Ele é estreito de propósito —
precisa de match positivo numa frase de recuperação **e** de nenhuma palavra de
julgamento (`_ADVICE_RE`: devo, vale a pena, recomenda, comprar, vender, tese,
risco…). "quanto tenho em cripto, devo aumentar?" carrega uma decisão e vai
para opus. **Na dúvida, opus** continua valendo.

**"fatura" vai sempre para opus** (2026-09-12): "paguei a fatura 3200" tem
verbo no passado + valor e cairia no haiku, que lançaria um gasto fantasma de
R$ 3.200 — cada compra já está no ledger. O match é `fatura\w*` (pega o plural
"faturas" e derivados como "faturamento") em `_ASKS_RE` e em `_ADVICE_RE`,
então sai do caminho rápido e do lookup.

O roteamento acontece ANTES de o turno adquirir o `_chat_turn.lock`. O modelo e
o tier usados ficam gravados na `ChatMessage`.

## Classificador de gasto

`classifier_service.py`. "gastei 42,90 no mercado ontem" → JSON estruturado
(`kind`, `amount_brl`, `category`, `description`, `occurred_on` com data relativa resolvida, `card` auto|none|nome, `installments`). haiku, workspace sem MCP, ~5s.

**Devolve RASCUNHO e não grava** (`POST /api/cashflow/classify` → `CashflowCreate`).
O usuário confirma no formulário — senão um erro de leitura entra calado no
ledger. Data malformada cai para hoje em vez de falhar a entrada inteira.

## Onde mexer quando…

| Quero… | Mexa em |
|---|---|
| mudar o comportamento permanente do comitê | `_STANDING_ORDERS` em `analysis_runner.py` |
| mudar o comportamento do consultor | `_CONSULTANT_ORDERS` em `chat_service.py` |
| mudar o formato do fechamento | `_SYNTHESIS_PROMPT` em `analysis_runner.py` |
| adicionar um MCP ao baseline | `_baseline_mcp_servers()` (ou `_KEY_GATED_MCP_SERVERS` se exigir chave) |
| mudar o texto de uma reunião | `app/agents_prompts/0N_*.j2` |
| mudar título/descrição das reuniões | `prompt_generator._PROMPT_DEFINITIONS` |
| adicionar um tipo de análise novo | escreva os `steps` e chame `run_chain` (veja `review_service`) |
| mudar timeouts, modelo ou effort | `app/config.py` / `.env` |
