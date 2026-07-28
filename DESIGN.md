# DESIGN.md

The system already in `frontend/src/app/globals.css`. Extend it; do not restyle
around it.

## Color

Cool neutrals, white panels, one teal accent. Light only — there is no dark
variant, by the owner's choice. Every value is OKLCH and every neutral is
tinted toward hue 250; the earlier warm tint (hue 75) read as yellowed paper
and was the "off-white" the owner disliked. Cards are pure white, which he
prefers, and lift off the page by contrast plus a 1px border rather than a
shadow. Strategy: **Restrained** — neutrals plus a single accent carrying
interaction and current state.

| Role | Token | Notes |
|---|---|---|
| Page | `--bg-primary` | Cool near-white, the default surface |
| Panel | `--bg-secondary` | Sidebar, table headers, code blocks |
| Raised | `--bg-card` / `--bg-elevated` | Pure white, a shade above the page |
| Ink | `--text-primary` / `--text-secondary` / `--text-muted` | Three steps, no more |
| Accent | `--accent` / `--accent-light` / `--accent-strong` | Teal. Interaction and current state only |
| Semantic | `--success` `--danger` `--warning` (+ `-light` pairs) | Money direction and risk |

Green means money in, red means money out. That is the only place semantic
color carries meaning without a text label beside it.

Never introduce a gradient. Never use a colored `border-left` as an accent.

## Type

- **Bricolage Grotesque** (`--font-heading`) — headings and large monetary
  display only. Never in labels, buttons, table cells, or form controls.
- **Plus Jakarta Sans** (`--font-body`) — everything else, including all data.
- `.tabular` applies `tabular-nums` and must be on every figure that can change,
  so digits do not jitter between refreshes.
- Section eyebrows: 11px, uppercase, `letter-spacing: 0.18em`, `--text-muted`.
- Fixed rem steps for UI. `clamp()` only on the hero monetary figures, which
  genuinely benefit from scaling between a 390px phone and a wide desktop.

## Mobile shell

The phone is the primary surface.

- Below `md`, the sidebar is replaced by a fixed bottom tab bar; above it, the
  sidebar returns and the tab bar disappears. One nav source of truth feeds
  both.
- The tab bar sits above `env(safe-area-inset-bottom)` so it clears the iPhone
  home indicator. Scrollable content reserves that height plus the bar.
- Tap targets are at least 44px. Inputs are at least 16px so iOS does not zoom
  the viewport on focus.
- Tables do not shrink to fit a phone. Below `md` each row becomes a stacked
  block; the table returns at `md`.

## Motion

150–250 ms, ease-out. State and feedback only: a value updating, a row
entering, a sheet opening. No page-load choreography, no decorative loops.
Framer Motion is already a dependency; reach for it only when CSS cannot do it.

## Components

Buttons, inputs and selects share one vocabulary across every screen: 1px
border in `--border`, 6px radius, accent focus ring via the global
`:focus-visible` rule. Loading is a skeleton in place of content, never a
spinner floating in the middle of a panel. Empty states state the fact and
offer the action, in that order, without exclamation marks.
