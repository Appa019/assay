"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from "recharts";
import type {
  BenchmarkPoint,
  PortfolioHistoryPoint,
  PortfolioSummary,
} from "@/lib/api";
import { formatBRL, formatDate, parseLocalDate } from "@/lib/format";
import { valuesHidden } from "@/lib/privacy";

/**
 * Categorical palette for the three mandate classes. Validated with the
 * dataviz six-checks script (all-pairs, light surface #fdfcfa): lightness
 * band, chroma floor, CVD ΔE 14.3, normal-vision ΔE 20.6, contrast ≥ 3:1.
 */
const CLASS_COLORS: Record<"fixed_income" | "stocks" | "crypto", string> = {
  fixed_income: "#00829b",
  stocks: "#c9662a",
  crypto: "#5c3ab8",
};

const CLASS_NAMES: Record<"fixed_income" | "stocks" | "crypto", string> = {
  fixed_income: "Renda fixa",
  stocks: "Ações B3",
  crypto: "Crypto",
};

/** Series color for "current" marks (equity curve, benchmark portfolio line). */
const ACTUAL_COLOR = CLASS_COLORS.fixed_income;

const AXIS_TICK = { fill: "var(--text-muted)", fontSize: 11 } as const;
/** Phone ticks drop a point so dense axes stop colliding at 390px. */
const AXIS_TICK_MOBILE = { fill: "var(--text-muted)", fontSize: 10 } as const;

/* ── Breakpoint ────────────────────────────────────────────────────── */

/** Mirrors Tailwind's `md` breakpoint (768px). */
const MOBILE_QUERY = "(max-width: 767px)";

let mobileMediaQuery: MediaQueryList | null = null;

const getMobileMediaQuery = (): MediaQueryList => {
  mobileMediaQuery ??= window.matchMedia(MOBILE_QUERY);
  return mobileMediaQuery;
};

const subscribeToBreakpoint = (onChange: () => void): (() => void) => {
  const query = getMobileMediaQuery();
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
};

/**
 * Chart geometry (axis width, tick density, pie radii) lives inside the SVG
 * and cannot be driven by CSS, so the breakpoint is read in JS.
 * `useSyncExternalStore` subscribes to matchMedia without ever setting state
 * from an effect body; the server snapshot assumes desktop and hydration
 * corrects it.
 */
const useIsMobile = (): boolean =>
  useSyncExternalStore(
    subscribeToBreakpoint,
    () => getMobileMediaQuery().matches,
    () => false
  );

/* ── Formatters ────────────────────────────────────────────────────── */

const compactBRL = (value: number): string => {
  if (valuesHidden()) return "R$ ••••";
  const compact = new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
  return `R$ ${compact}`;
};

/** "01 de jul." — roomy label for desktop time axes. */
const formatTickDate = (ts: number): string =>
  new Date(ts).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "short",
  });

/** "01/07" — half the width, so phone time axes keep more than two ticks. */
const formatTickDateShort = (ts: number): string =>
  new Date(ts).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
  });

const TooltipShell = ({ children }: { children: React.ReactNode }) => (
  <div
    // The phone cap keeps the floating tooltip inside the chart box so it can
    // never push the page wider than the viewport.
    className="px-3.5 py-2.5 rounded-md text-xs shadow-sm max-w-[15rem] md:max-w-none"
    style={{
      background: "var(--bg-card)",
      border: "1px solid var(--border-strong)",
      color: "var(--text-primary)",
    }}
  >
    {children}
  </div>
);

const SwatchRow = ({
  color,
  label,
  value,
}: {
  color: string;
  label: string;
  value: string;
}) => (
  <div className="flex items-center gap-2 py-0.5">
    <span
      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
      style={{ background: color }}
    />
    <span style={{ color: "var(--text-secondary)" }}>{label}</span>
    <span className="ml-auto pl-4 font-semibold tabular">{value}</span>
  </div>
);

type ChartTooltipProps = TooltipContentProps<TooltipValueType, number | string>;

/* ── Allocation donut ──────────────────────────────────────────────── */

type DonutDatum = {
  key: "fixed_income" | "stocks" | "crypto";
  name: string;
  value: number;
  pct: number;
};

const DonutTooltip = ({ active, payload }: ChartTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0].payload as DonutDatum;
  return (
    <TooltipShell>
      <SwatchRow
        color={CLASS_COLORS[datum.key]}
        label={datum.name}
        value={`${formatBRL(datum.value)} · ${datum.pct.toFixed(1)}%`}
      />
    </TooltipShell>
  );
};

export const AllocationDonut = ({
  portfolio,
}: {
  portfolio: PortfolioSummary;
}) => {
  const isMobile = useIsMobile();

  const data: DonutDatum[] = (
    [
      {
        key: "fixed_income",
        value: portfolio.allocation.fixed_income,
        pct: portfolio.allocation.fixed_income_pct,
      },
      {
        key: "stocks",
        value: portfolio.allocation.stocks,
        pct: portfolio.allocation.stocks_pct,
      },
      {
        key: "crypto",
        value: portfolio.allocation.crypto,
        pct: portfolio.allocation.crypto_pct,
      },
    ] as const
  )
    .filter((d) => d.value > 0)
    .map((d) => ({ ...d, name: CLASS_NAMES[d.key] }));

  if (data.length === 0) {
    return (
      <p className="text-sm py-10 text-center" style={{ color: "var(--text-muted)" }}>
        Sem posições ainda: o donut aparece com a primeira compra.
      </p>
    );
  }

  return (
    // The legend sits below the donut on phones instead of beside it.
    <div className="flex flex-col md:flex-row items-center gap-6 md:gap-8">
      <div className="shrink-0 w-[150px] h-[150px] md:w-[180px] md:h-[180px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={DonutTooltip} />
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius={isMobile ? 44 : 54}
              outerRadius={isMobile ? 70 : 84}
              stroke="var(--bg-card)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              {data.map((entry) => (
                <Cell key={entry.key} fill={CLASS_COLORS[entry.key]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-full md:w-auto space-y-2.5 text-sm min-w-0">
        {data.map((entry) => (
          <li key={entry.key} className="flex items-center gap-2.5">
            <span
              className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
              style={{ background: CLASS_COLORS[entry.key] }}
            />
            <span style={{ color: "var(--text-secondary)" }}>{entry.name}</span>
            <span
              className="tabular font-semibold ml-auto pl-4"
              style={{ color: "var(--text-primary)" }}
            >
              {entry.pct.toFixed(1)}%
            </span>
            <span
              className="tabular text-xs w-24 text-right shrink-0"
              style={{ color: "var(--text-muted)" }}
            >
              {formatBRL(entry.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/* ── Equity curve ──────────────────────────────────────────────────── */

type EquityDatum = {
  ts: number;
  snapshot_date: string;
  total_value: number;
};

const EquityTooltip = ({ active, payload }: ChartTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0].payload as EquityDatum;
  return (
    <TooltipShell>
      <p className="mb-0.5" style={{ color: "var(--text-muted)" }}>
        {formatDate(datum.snapshot_date)}
      </p>
      <p className="font-semibold tabular">{formatBRL(datum.total_value)}</p>
    </TooltipShell>
  );
};

export const EquityCurveChart = ({
  history,
}: {
  history: PortfolioHistoryPoint[];
}) => {
  const isMobile = useIsMobile();

  const data: EquityDatum[] = useMemo(
    () =>
      [...history]
        .map((point) => ({
          ts: parseLocalDate(point.snapshot_date).getTime(),
          snapshot_date: point.snapshot_date,
          total_value: point.total_value,
        }))
        .sort((a, b) => a.ts - b.ts),
    [history]
  );

  return (
    <div className="w-full min-w-0 h-[210px] md:h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={isMobile ? formatTickDateShort : formatTickDate}
            tick={isMobile ? AXIS_TICK_MOBILE : AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: "var(--border-strong)" }}
            interval={isMobile ? "preserveStartEnd" : "preserveEnd"}
            minTickGap={isMobile ? 44 : 48}
          />
          <YAxis
            tickFormatter={compactBRL}
            tick={isMobile ? AXIS_TICK_MOBILE : AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={isMobile ? 62 : 72}
            tickCount={isMobile ? 4 : undefined}
            domain={["auto", "auto"]}
          />
          <Tooltip
            content={EquityTooltip}
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
          />
          <Area
            type="monotone"
            dataKey="total_value"
            stroke={ACTUAL_COLOR}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill={ACTUAL_COLOR}
            fillOpacity={0.08}
            dot={false}
            activeDot={{
              r: 4,
              fill: ACTUAL_COLOR,
              stroke: "var(--bg-card)",
              strokeWidth: 2,
            }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

/* ── Benchmark: portfolio TWR vs CDI · IBOV · BTC (rebased 100) ────── */

type BenchKey = "portfolio" | "cdi" | "ibov" | "btc";

/**
 * Portfolio/IBOV/BTC reuse the validated categorical trio; CDI is the
 * risk-free reference and wears a deliberate de-emphasis gray (identity via
 * legend + tooltip), keeping the colored series within the all-pairs-safe cap.
 */
const BENCH_SERIES: {
  key: BenchKey;
  label: string;
  color: string;
  width: number;
}[] = [
  { key: "portfolio", label: "Carteira", color: CLASS_COLORS.fixed_income, width: 2.5 },
  { key: "cdi", label: "CDI", color: "#6e695f", width: 1.5 },
  { key: "ibov", label: "IBOV", color: CLASS_COLORS.stocks, width: 1.5 },
  { key: "btc", label: "BTC", color: CLASS_COLORS.crypto, width: 1.5 },
];

type BenchDatum = {
  ts: number;
  date: string;
  portfolio: number;
  cdi: number | null;
  ibov: number | null;
  btc: number | null;
};

const BenchmarkTooltip = ({ active, payload }: ChartTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0].payload as BenchDatum;
  return (
    <TooltipShell>
      <p className="mb-1" style={{ color: "var(--text-muted)" }}>
        {formatDate(datum.date)}
      </p>
      {BENCH_SERIES.map((series) => {
        const value = datum[series.key];
        if (value === null || value === undefined) return null;
        if (!payload.some((entry) => entry.dataKey === series.key)) return null;
        return (
          <SwatchRow
            key={series.key}
            color={series.color}
            label={series.label}
            value={value.toFixed(1)}
          />
        );
      })}
    </TooltipShell>
  );
};

export const BenchmarkChart = ({ series }: { series: BenchmarkPoint[] }) => {
  const isMobile = useIsMobile();
  const [hidden, setHidden] = useState<Partial<Record<BenchKey, boolean>>>({});

  const data: BenchDatum[] = useMemo(
    () =>
      [...series]
        .map((point) => ({
          ts: parseLocalDate(point.date).getTime(),
          date: point.date,
          portfolio: point.portfolio,
          cdi: point.cdi,
          ibov: point.ibov,
          btc: point.btc,
        }))
        .sort((a, b) => a.ts - b.ts),
    [series]
  );

  const toggle = (key: BenchKey) =>
    setHidden((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="space-y-3">
      {/* Clickable legend: toggles each series on/off. Sits above the plot on
          every width, with 44px touch targets on phones. */}
      <div className="flex items-center gap-1 md:gap-4 flex-wrap text-xs">
        {BENCH_SERIES.map((entry) => {
          const off = hidden[entry.key] === true;
          return (
            <button
              key={entry.key}
              type="button"
              onClick={() => toggle(entry.key)}
              aria-pressed={!off}
              title={off ? `Mostrar ${entry.label}` : `Ocultar ${entry.label}`}
              className="flex items-center justify-center md:justify-start gap-1.5 min-h-11 min-w-11 px-3 md:min-h-0 md:min-w-0 md:px-1.5 md:py-1 rounded-md transition-opacity"
              style={{ opacity: off ? 0.35 : 1 }}
            >
              <span
                className="inline-block w-3.5 rounded-full shrink-0"
                style={{ background: entry.color, height: entry.width }}
              />
              <span
                style={{
                  color: "var(--text-secondary)",
                  textDecoration: off ? "line-through" : "none",
                }}
              >
                {entry.label}
              </span>
            </button>
          );
        })}
      </div>
      <div className="w-full min-w-0 h-[220px] md:h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: isMobile ? 0 : -8 }}
          >
            <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={isMobile ? formatTickDateShort : formatTickDate}
              tick={isMobile ? AXIS_TICK_MOBILE : AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--border-strong)" }}
              interval={isMobile ? "preserveStartEnd" : "preserveEnd"}
              minTickGap={isMobile ? 44 : 48}
            />
            <YAxis
              tick={isMobile ? AXIS_TICK_MOBILE : AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={isMobile ? 32 : 48}
              tickCount={isMobile ? 4 : undefined}
              domain={["auto", "auto"]}
            />
            <Tooltip
              content={BenchmarkTooltip}
              cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            />
            {BENCH_SERIES.map((entry) => (
              <Line
                key={entry.key}
                dataKey={entry.key}
                hide={hidden[entry.key] === true}
                type="monotone"
                stroke={entry.color}
                strokeWidth={entry.width}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={false}
                connectNulls={false}
                activeDot={{
                  r: 4,
                  fill: entry.color,
                  stroke: "var(--bg-card)",
                  strokeWidth: 2,
                }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
