"use client";

import { motion } from "framer-motion";
import type { PortfolioSummary } from "@/lib/api";
import { formatBRL } from "@/lib/format";

/**
 * Small CSS-drawn figures for the overview page: money in vs money out, where
 * the month's spending went, and how far each class sits from the mandate.
 *
 * They are bar lists rather than Recharts plots on purpose — every row already
 * carries its label and its value, so an SVG plot would add a runtime and an
 * axis without adding a fact. The time series and the composition donut stay in
 * `portfolio-charts.tsx`, which is where the plotted charts live.
 */

/**
 * Class hues mirror the validated categorical trio in `portfolio-charts.tsx`
 * (that module exports components only), so the donut and these rails name the
 * same class with the same color.
 */
const CLASS_COLORS = {
  fixed_income: "#00829b",
  stocks: "#c9662a",
  crypto: "#5c3ab8",
} as const;

type ClassKey = keyof typeof CLASS_COLORS;

/** Every expense bar wears one color: length is the only variable encoded. */
const EXPENSE_BAR = "color-mix(in oklch, var(--danger) 68%, var(--bg-card))";

const TRANSITION = { duration: 0.22, ease: "easeOut" } as const;

/** Guards against NaN and division blow-ups before a width reaches the DOM. */
const clampPct = (value: number): number =>
  Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;

const oneDecimal = (value: number): string =>
  value.toLocaleString("pt-BR", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

/**
 * One rail. Square at the baseline, rounded at the data end; the track is a
 * lighter step of the fill's own hue so the unfilled part still reads as state.
 */
const Bar = ({
  pct,
  color,
  track,
  className,
}: {
  pct: number;
  color: string;
  track: string;
  className: string;
}) => (
  <div
    className={`w-full overflow-hidden ${className}`}
    style={{ background: track, borderRadius: 3 }}
  >
    <motion.div
      className="h-full"
      style={{ background: color, borderRadius: "3px 4px 4px 3px" }}
      initial={{ width: 0 }}
      animate={{ width: `${clampPct(pct)}%` }}
      transition={TRANSITION}
    />
  </div>
);

/* ── Month: money in vs money out ──────────────────────────────────── */

/**
 * Both rails share one scale, so the longer bar is literally the bigger number
 * — the answer to "did I spend more than I earned this month?" without reading
 * a single digit.
 */
export const FlowRails = ({
  income,
  expense,
}: {
  income: number;
  expense: number;
}) => {
  const scale = Math.max(income, expense, 1);
  const rows = [
    {
      label: "Entrou",
      value: income,
      color: "var(--success)",
      track: "var(--success-light)",
    },
    {
      label: "Saiu",
      value: expense,
      color: "var(--danger)",
      track: "var(--danger-light)",
    },
  ] as const;

  return (
    <div className="space-y-4">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="flex items-baseline justify-between gap-3">
            <span
              className="text-[11px] font-medium uppercase tracking-[0.16em]"
              style={{ color: "var(--text-muted)" }}
            >
              {row.label}
            </span>
            <span
              className="tabular text-[15px] font-semibold"
              style={{ color: row.color }}
            >
              {formatBRL(row.value)}
            </span>
          </div>
          <div className="mt-2">
            <Bar
              className="h-2.5"
              pct={(row.value / scale) * 100}
              color={row.color}
              track={row.track}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

/* ── Month: where the money went ───────────────────────────────────── */

export type CategorySlice = {
  category: string;
  total_brl: number;
};

/** Ranked spending by category — bars sorted by the caller, longest first. */
export const CategoryBars = ({ slices }: { slices: CategorySlice[] }) => {
  const max = slices.reduce((acc, slice) => Math.max(acc, slice.total_brl), 0) || 1;

  return (
    <ul className="space-y-3">
      {slices.map((slice) => (
        <li key={slice.category}>
          <div className="flex items-baseline justify-between gap-3">
            <span
              // first-letter, not `capitalize`: the ledger stores categories in
              // lowercase and a folded "outras 3 categorias" row must not turn
              // into Title Case.
              className="truncate text-[13px] first-letter:uppercase"
              style={{ color: "var(--text-primary)" }}
            >
              {slice.category}
            </span>
            <span
              className="tabular shrink-0 text-[13px]"
              style={{ color: "var(--text-secondary)" }}
            >
              {formatBRL(slice.total_brl)}
            </span>
          </div>
          <div className="mt-1.5">
            <Bar
              className="h-1.5"
              pct={(slice.total_brl / max) * 100}
              color={EXPENSE_BAR}
              track="var(--bg-secondary)"
            />
          </div>
        </li>
      ))}
    </ul>
  );
};

/* ── Portfolio: distance from the mandate ──────────────────────────── */

const MANDATE_ROWS: { key: ClassKey; label: string }[] = [
  { key: "fixed_income", label: "Renda fixa" },
  { key: "stocks", label: "Ações B3" },
  { key: "crypto", label: "Crypto" },
];

/**
 * One rail per class on a fixed 0–100% scale, with a tick where the mandate
 * says the class should land. An empty portfolio drops the deviation line —
 * "−35 pp" on every class states nothing beyond "there is nothing here yet".
 */
export const MandateRails = ({ portfolio }: { portfolio: PortfolioSummary }) => {
  const invested = portfolio.total_value > 0;
  const actual: Record<ClassKey, number> = {
    fixed_income: portfolio.allocation.fixed_income_pct,
    stocks: portfolio.allocation.stocks_pct,
    crypto: portfolio.allocation.crypto_pct,
  };

  return (
    <ul className="space-y-5">
      {MANDATE_ROWS.map(({ key, label }) => {
        const target = portfolio.target_allocation[key];
        const deviation = portfolio.deviation[key];
        return (
          <li key={key}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                {label}
              </span>
              <span
                className="tabular text-[15px] font-semibold"
                style={{ color: "var(--text-primary)" }}
              >
                {oneDecimal(actual[key])}%
              </span>
            </div>
            <div className="relative mt-2">
              <Bar
                className="h-2.5"
                pct={actual[key]}
                color={CLASS_COLORS[key]}
                track={`color-mix(in oklch, ${CLASS_COLORS[key]} 13%, var(--bg-card))`}
              />
              <span
                aria-hidden
                className="absolute -top-1 -bottom-1 w-0.5"
                style={{
                  left: `${clampPct(target)}%`,
                  background: "var(--text-secondary)",
                }}
              />
            </div>
            <p
              className="tabular mt-1.5 text-right text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              alvo {target.toFixed(0)}%
              {invested && (
                <>
                  {" · "}
                  <span
                    style={{
                      color:
                        Math.abs(deviation) > 5
                          ? "var(--warning)"
                          : "var(--text-muted)",
                    }}
                  >
                    {deviation > 0 ? "+" : ""}
                    {oneDecimal(deviation)} pp
                  </span>
                </>
              )}
            </p>
          </li>
        );
      })}
    </ul>
  );
};
