# 07 · Frontend

Next.js 16 (App Router) · React 19 · TypeScript strict · Tailwind v4 ·
Framer Motion · Recharts · Lucide · react-markdown. Gerenciador: **pnpm**.

> O contrato visual completo está em **`DESIGN.md`** (raiz). Este documento é o
> mapa do código. Leia os dois antes de mexer em `.tsx`.

## Regra número um

Antes de terminar qualquer trabalho de frontend: **"alguém saberia na hora que
uma IA fez isso?"** Se sim, refaça. Sem gradiente, sem glassmorphism, sem ícone
grande em quadrado arredondado sobre cada título, sem 4 cards de stat idênticos,
sem Inter/Roboto/system-ui.

## Estrutura

```
src/
├── app/
│   ├── layout.tsx            fontes (next/font), metadata, viewport, PWA
│   ├── globals.css           TOKENS (oklch) + regras de iOS + reset
│   └── (dashboard)/
│       ├── layout.tsx        <ValuesShell> + <PrivacyToggle> + <Sidebar> +
│       │                     <main> + <MobileNav>
│       ├── page.tsx          / — Visão geral (727 linhas)
│       ├── consultor/        chat
│       ├── extrato/          ?aba=mes (ledger + fatura) | ?aba=fluxo (previsto)
│       ├── investimentos/    casca com 4 sub-abas na URL
│       ├── ativos/           AtivosView (1423 linhas — o maior arquivo)
│       ├── aporte/           AporteView + [id]/ (acompanhamento)
│       ├── relatorios/       RelatoriosView
│       ├── ir/               IrView
│       ├── configuracoes/    diagnóstico, push, cadastro de cartões
│       └── error.tsx         boundary de erro
├── components/               11 componentes (+ privacy-toggle, values-shell)
├── hooks/                    use-portfolio · use-cashflow · use-macro ·
│                             use-portfolio-history · use-cadence · use-cards
└── lib/                      api.ts · nav.ts · format.ts · privacy.ts
```

## Navegação — `lib/nav.ts` é a fonte única

**Quatro abas.** Mexa em `NAV_ITEMS`, nunca nos componentes: `<Sidebar>` (≥md) e
`<MobileNav>` (<md) leem do mesmo array.

| Aba | Rota | Papel |
|---|---|---|
| Visão geral | `/` | patrimônio + saldo do mês + alocação vs mandato + benchmark + ordens pendentes + macro |
| Consultor | `/consultor` | o chat (registrar gasto, pedir aporte, tirar dúvida) |
| Extrato | `/extrato` | casca de 2 sub-abas: **Mês** (ledger, por categoria, com exclusão) e **Fluxo** (6 meses de entrada × saída previstas) |
| Investimentos | `/investimentos` | casca de 4 sub-abas |

`/extrato` hospeda duas sub-abas na URL (`?aba=mes|fluxo`): `MesView` mora na
própria `page.tsx` e `FluxoView` em `extrato/fluxo-view.tsx`. No Fluxo, as
barras de entrada e saída de todos os meses usam **uma escala compartilhada** —
é o que torna visível o aperto e o alívio quando a última parcela cai; tocar o
mês abre a composição (recorrência com o dia, parcela `3/10`, fatura vencendo).

`/investimentos` hospeda as views por sub-aba na URL
(`?aba=carteira|aportar|analises|ir`). As páginas correspondentes exportam o
componente **por nome** (`AtivosView`, `AporteView`, `RelatoriosView`, `IrView`)
além do default — as rotas antigas continuam vivas para deep link.

## Design system (`globals.css`)

Cool neutrals, painéis brancos, um accent teal. **Light only** — não existe
variante escura, por escolha do dono.

Todos os valores em **oklch**, neutros tintados para o hue **250** (a versão
quente, hue 75, lia como papel amarelado — foi rejeitada). Cards são **branco
puro** (`--bg-card: #ffffff`), preferido pelo cliente, e sobem da página por
contraste + borda de 1px, **nunca por sombra**.

| Papel | Token |
|---|---|
| Página | `--bg-primary` |
| Painel (sidebar, header de tabela, code block) | `--bg-secondary` |
| Elevado | `--bg-card` / `--bg-elevated` (`#fff`) |
| Texto | `--text-primary` / `--text-secondary` / `--text-muted` — três degraus, não mais |
| Accent | `--accent` / `--accent-light` / `--accent-strong` — teal, só interação e estado atual |
| Semântico | `--success` `--danger` `--warning` (+ pares `-light`) |
| Bordas | `--border` / `--border-strong` |

Verde = dinheiro entrando, vermelho = saindo. É o único lugar onde a cor carrega
significado sem rótulo ao lado.

**Nunca** introduza gradiente. **Nunca** use `border-left` colorido como accent.

### Tipografia

- **Bricolage Grotesque** (`--font-heading`) — títulos e display monetário
  grande **apenas**. Nunca em label, botão, célula de tabela ou controle.
- **Plus Jakarta Sans** (`--font-body`) — todo o resto, inclusive dados.
- `.tabular` (`tabular-nums`) em **toda** figura que pode mudar, para os dígitos
  não tremerem entre refreshes.
- Eyebrow de seção: 11px, uppercase, `letter-spacing: 0.18em`, `--text-muted`.
- `clamp()` só nas figuras monetárias heroicas; o resto usa passos fixos em rem.

Carregadas por `next/font/google` no `layout.tsx` — **self-hosted no build**,
nenhuma requisição a fonte externa em runtime.

## Regras de iOS (não negocie)

O iPhone é a superfície primária. Estas regras estão em `globals.css` e no
`layout.tsx`:

- **Controles ≥16px** de fonte — abaixo disso o Safari dá zoom no viewport e não
  volta.
- **Alvos de toque ≥44px.**
- `viewport-fit=cover` no viewport + `env(safe-area-inset-bottom)` na barra
  inferior, para limpar o home indicator. O conteúdo rolável reserva essa
  altura + a barra (`pb-28` no `<main>`).
- `themeColor` casa com `--bg-primary` (`#f6f7f9`) para a status bar se fundir
  na página.
- **Tabelas não encolhem** para caber no celular: abaixo de `md` cada linha vira
  bloco empilhado; a tabela volta em `md`.

### PWA

`public/manifest.webmanifest` + `apple-icon.png` + `icon.svg`. "Adicionar à Tela
de Início" abre em tela cheia, sem barra do Safari. Os ícones são gerados por
`scripts/build_icon.py` — **não edite à mão**.

## Motion

150–250ms, ease-out. Só estado e feedback: um valor atualizando, uma linha
entrando, uma folha abrindo. Sem coreografia de carregamento de página, sem loop
decorativo. Framer Motion já é dependência — use só quando CSS não resolve.

Loading é **skeleton no lugar do conteúdo**, nunca spinner flutuando no meio de
um painel. E só onde o carregamento passa de ~500ms.

## Camada de dados

`lib/api.ts` (649 linhas) é o cliente tipado — **todo** fetch passa por lá.
Tipos espelham os schemas Pydantic. `ApiError` carrega status + `detail`.

`API_BASE` vem de `NEXT_PUBLIC_API_BASE_URL`; **vazio é o normal** — assim as
chamadas são relativas, o rewrite do Next cuida do resto e não há CORS.

Os hooks (`use-portfolio`, `use-cashflow`, …) encapsulam fetch + loading + erro
+ refetch. `use-cashflow` busca lançamentos e resumo **em par**, para a lista e o
cabeçalho nunca discordarem depois de uma escrita.

**Estados honestos:** se o backend caiu, mostre `<WifiOff>` e diga isso — nunca
renderize um zero que parece saldo real.

## Olhinho (ocultar valores)

`lib/privacy.ts` é um store mínimo (`useSyncExternalStore`) persistido em
`localStorage` (`assay.values-hidden`). Os três formatadores de moeda de
`lib/format.ts` (`formatBRL`, `formatBRLCompact`, `formatAmount`) leem o flag
e devolvem `••••` quando oculto — percentuais e quantidades continuam
visíveis. Como são funções puras chamadas no render, `ValuesShell` (no
layout) remonta a página ao alternar (`key` no wrapper): estado local da
tela reseta, o que é aceitável para uma ação rara. O botão (`PrivacyToggle`,
Lucide `Eye`/`EyeOff`) vive na sidebar e flutua ao lado do sino no celular.
Ao abrir o app com o flag salvo há um frame com valores visíveis antes da
remontagem — trade-off documentado, não bug. `/consultor` é isento dessa
remontagem: a tela não formata dinheiro nenhum, e remontar apagaria o
rascunho digitado e os anexos selecionados que ficam no estado do chat.

## Componentes

| Componente | Papel |
|---|---|
| `sidebar.tsx` / `mobile-nav.tsx` | as duas caras da mesma navegação |
| `portfolio-charts.tsx` | `AllocationDonut`, `EquityCurveChart`, `BenchmarkChart` (Recharts) |
| `overview-charts.tsx` | `FlowRails`, `MandateRails`, `CategoryBars` — as visualizações próprias da home |
| `orders-panel.tsx` | folha de ordens com executar/pular inline; ticket e stop copiáveis em formato de corretora (vírgula decimal) |
| `analysis-flow.tsx` | um aporte em 4 estados: agendado (`scheduled_for`, sem spinner), rodando (polling), parou (`describeRunFailure`) e concluído (ordens → fechamento → atas recolhidas) |
| `markdown-viewer.tsx` | renderiza memos do comitê (remark-gfm + rehype-slug); `maxHeight` só vale de `md` para cima |
| `download-button.tsx` | baixa um relatório como `.md` |

## Padrões de código (obrigatórios)

- TypeScript **strict**. Sem `any`, sem `@ts-ignore`.
- **Named exports**, exceto onde o Next exige default (page, layout).
- `const`/`let` — nunca `var`.
- Arrow function para componente e callback.
- `async`/`await` — nunca `.then()` cru.
- Path alias `@/`.
- Early return em vez de aninhar condicional.

## Antes de commitar frontend

```bash
cd frontend && pnpm lint && pnpm type-check && pnpm build
```

⚠️ `pnpm build` **assa** o rewrite de `/api/*`. Se `BACKEND_ORIGIN` mudar, tem
que rebuildar — setar na hora do `next start` não faz nada.
