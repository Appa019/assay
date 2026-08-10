# 01 · Produto

## O problema que o app resolve

Pedro tinha duas coisas separadas: um controle de gastos (que ele não mantinha)
e uma carteira de investimentos (que ele decidia no escuro). O dinheiro é o
mesmo. O produto junta os dois e responde uma pergunta só: **"como eu estou
indo?"** — sem obrigar o dono a pensar em qual sistema guarda o quê.

Em cima disso, a parte cara: **decidir onde aportar**. Um investidor pessoa
física não tem mesa de research. O Assay simula uma: um comitê multipersona de
IA que pesquisa ao vivo, debate em 5 reuniões e entrega uma folha de ordens.

## Usuário

**Exatamente um: Pedro.** Técnico, financeiramente letrado, lê números
fluentemente. Sabe o que é Sharpe ratio; não precisa de "Patrimônio (o valor
total dos seus investimentos)".

Nunca haverá segundo usuário, time, permissões ou compartilhamento. **Não
projete para eles.** Sem onboarding, sem tutorial, sem empty state pedagógico.

## Contexto primário de uso

**iPhone 13 Pro, uma mão, sobre VPN Tailscale.** Esta é a superfície padrão, não
um detalhe. Dois momentos recorrentes:

1. Em pé numa loja, logo depois de pagar: registrar o gasto em menos de 5
   segundos, com um polegar.
2. Na cama ou no transporte: bater o olho no saldo do mês, no patrimônio e em
   ordens pendentes.

O desktop é secundário — serve para os artefatos longos: memos do comitê,
relatório de IR, tabela completa de ativos.

**Desenhe mobile-first e deixe o desktop herdar.** O inverso produz layout
espremido.

## Marca e tom

Editorial e silencioso. Mais perto de um jornal financeiro bem diagramado do que
de um app de fintech. Números são a coisa mais alta na tela; a moldura em volta
é quase muda.

- Wordmark: **Assay** (era "Mesa" até 2026-07-29).
- Marca de aplicativo: hexágono isométrico subdividido em retículo rombóico
  sobre campo `#060a11`. Deliberadamente abstrata, sem relação com a palavra
  "assay". **Fonte única: `scripts/build_icon.py`** — não edite os assets à mão.
- Interface toda em pt-BR. Direto, técnico, sem enfeite e sem torcida.
  "Nenhum lançamento neste mês", não "Você ainda não tem lançamentos! 🎉".

### Anti-referências (o que NÃO ser)

| Não | Por quê |
|---|---|
| Nubank / Neon / C6 | roxo, tudo arredondado, mascote, confete, gamificação |
| Cosplay de Bloomberg | neon no preto, grid monoespaçado denso, urgência falsa |
| Dashboard SaaS genérico | 4 cards de stat idênticos, ícone em quadrado arredondado sobre cada título |
| "Wealth management" azul-marinho e dourado | é a primeira coisa que um modelo faz ao ouvir "finanças" |

## Princípios estratégicos

1. **Registrar um gasto é a ação mais frequente do produto.** Tem que ser
   alcançável em um toque de qualquer lugar e concluível sem sair da página.
   Não é modal. O caminho normal é contar ao consultor no chat.
2. **Investimentos e finanças pessoais são pares.** Nenhum é sub-seção do outro.
   A tela inicial mostra os dois.
3. **A IA é ferramenta, não personalidade.** A saída do comitê é documento e
   ordem, nunca balãozinho de chat fingindo ser amigo.
4. **Confiança vem de precisão.** Números tabulares, datas explícitas, estados
   vazios e de erro honestos. Se o backend caiu, diga isso — não mostre um zero
   que parece saldo real.
5. **Local e privado.** Sem telemetria, sem fonte externa em runtime, sem
   terceiro vendo esses dados. A interface pode dizer isso baixinho.

## Mandato de investimento (contrato com o comitê)

Três classes, **apenas**:

| Classe | Regra |
|---|---|
| **Renda Fixa** | Só **CDB Bradesco 100% do CDI com liquidez diária** — instrumento único e fixo (regra do cliente, 2026-08-10). O comitê decide QUANTO, nunca QUAL. **Nada** de outros emissores, CDB de prazo, Tesouro, LCI/LCA, debênture ou fundo de RF. |
| **Ações** | Só equities listadas na B3 (ON/PN/UNIT). **Nada** de FII, ETF, BDR ou internacional. |
| **Crypto** | Mandato **agressivo** ("sonhar alto"): alto upside, com gestão de risco. Exposição em USD só via stablecoin (USDC). |

Alvos de alocação padrão (`.env`): RF 35% · Ações 40% · Crypto 25%. Precisam
somar 1.0 — `app/config.py` valida e explode no boot se não somarem.

O mandato aparece em **quatro** lugares e precisa continuar coerente nos quatro:
ordens permanentes do agente, preâmbulo do ciclo, prompt de síntese e cabeçalho
dos 5 templates Jinja2.

### Preferências do cliente (informação LOCAL — não vaza para os prompts)

Estas são para você, Claude, não para o comitê. **Os prompts são agnósticos de
plataforma de propósito** — corretora e exchange são decisão do usuário na hora
de executar a folha de ordens.

- Corretora B3 preferida: a corretora do banco, para ações e CDB.
- Crypto majors (BTC/ETH): Mercado Bitcoin, Binance BR, Bitso, Coinext.
- Alts de menor liquidez: Binance BR.
- DeFi yield (USDC/USDT/USDe): wallet própria (MetaMask) + Aave / Pendle /
  Spark / Lido / Morpho.

## O que o produto deliberadamente NÃO faz

- **Não executa ordem.** Ele recomenda; quem compra e vende é o Pedro na
  corretora. O sistema só registra o que aconteceu.
- **Não substitui contador.** A apuração de IR é um mapa simplificado (sem
  day-trade, sem JCP/dividendos, sem custo operacional).
- **Não tem autenticação.** É single-user atrás de VPN. Não introduza Supabase
  Auth, RLS, login ou sessão — foi removido de propósito.
- **Não usa Playwright para operar corretora.** Playwright existe só como MCP de
  pesquisa do agente.
- **Não tem nuvem.** Sem Supabase, sem Vercel para o app (o `.vercel/` no
  frontend é resíduo antigo).
