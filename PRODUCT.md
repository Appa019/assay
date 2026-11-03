# PRODUCT.md

## Register

`product` — this is a working tool, not a marketing surface. Design serves the
task; the interface should disappear behind the numbers.

## Product purpose

A private money cockpit for one person. Two domains that used to be separate
and are now one product:

1. **Finanças pessoais** — day-to-day expenses and income (`CashflowEntry`).
   Logged by the owner directly in the app, or by an AI
   consultant that reads photographed receipts and bank statements.
2. **Investimentos** — an ad-hoc contribution ledger driven by an autonomous
   multi-persona AI committee. Portfolio, orders, tax, weekly reports.

The money is the same money. The product's job is to answer "how am I doing?"
across both without making the owner think about which system holds what.

## Users

Exactly one: Pedro, the owner. Technical, financially literate, reads numbers
fluently. No onboarding, no tutorials, no empty-state hand-holding beyond what
a first-run screen genuinely needs. He knows what a Sharpe ratio is; he does
not need "Portfolio (the total value of your investments)".

There will never be a second user, a team, permissions, or sharing. Do not
design for them.

## Primary context of use

**An iPhone 13 Pro, held one-handed, over a Tailscale VPN.** This is the
default surface now, not an afterthought. Two recurring moments:

- Standing in a store or just after paying for something: log the expense in
  under five seconds, one thumb, without hunting.
- Lying in bed or on a commute: glance at the month's net, the portfolio value,
  whether any order is pending.

A desktop browser is the secondary surface, used for the long-form artifacts:
committee memos, the tax report, the full asset table.

Design mobile-first and let the desktop inherit. The reverse produces a
squeezed desktop layout, which is what exists today.

## Brand and tone

Editorial and quiet. Closer to a well-set financial newspaper than to a
fintech app. Bricolage Grotesque (sans) for display figures over Plus Jakarta
Sans body, cool neutrals tinted toward hue 250 with pure white panels, one deep
indigo accent for interaction. Numbers are the loudest thing on screen; the
chrome around them is nearly silent.

Portuguese (pt-BR) throughout the interface. Direct, technical, no filler and
no cheerleading. "Nenhum lançamento neste mês", not "Você ainda não tem
lançamentos! Que tal começar agora? 🎉".

## Anti-references

Explicitly not these:

- **Nubank / Neon / C6 consumer-fintech.** Purple, rounded everything, mascots,
  celebratory confetti, gamified streaks.
- **Bloomberg terminal cosplay.** Neon on black, dense monospace grids,
  fake urgency.
- **Generic SaaS dashboard.** Identical stat cards in a four-across grid,
  icon-in-a-rounded-square above every heading, gradient hero metric.
- **Navy-and-gold "wealth management".** The first thing a model reaches for
  when it hears the word finance.

## Strategic principles

- **Logging an expense is the most frequent action in the product.** It should
  be reachable in one tap from anywhere and completable without leaving the
  page. It is not a modal.
- **Investments and personal finance are peers.** Neither is a sub-section of
  the other. The home screen shows both.
- **The AI is a tool, not a personality.** Committee output is presented as
  documents and orders, never as chat bubbles pretending to be a friend.
- **Trust comes from precision.** Tabular figures, explicit dates, honest empty
  and error states. If the backend is down, say so plainly rather than showing
  a zero that looks like a real balance.
- **Local and private.** No telemetry, no external fonts at runtime, no third
  party seeing this data. The interface can say so quietly.
