"use client";

import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
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

/** Series color for "current" marks; de-emphasis gray for the target reference. */
const ACTUAL_COLOR = CLASS_COLORS.fixed_income;
const TARGET_COLOR = "#cfc9bd";

const AXIS_TICK = { fill: "var(--text-muted)", fontSize: 11 } as const;

const compactBRL = (value: number): string => {
  const compact = new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
  return `R$ ${compact}`;
};

const TooltipShell = ({ children }: { children: React.ReactNode }) => (
  <div
    className="px-3.5 py-2.5 rounded-md text-xs shadow-sm"
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

const ChartLegend = ({
  items,
}: {
  items: { color: string; label: string }[];
}) => (
  <div className="flex items-center gap-5 text-xs">
    {items.map((item) => (
      <span key={item.label} className="flex items-center gap-1.5">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full"
          style={{ background: item.color }}
        />
        <span style={{ color: "var(--text-secondary)" }}>{item.label}</span>
      </span>
    ))}
  </div>
);

/* ── Allocation: actual vs target grouped bars ─────────────────────── */

type AllocationDatum = {
  name: string;
  atual: number;
  alvo: number;
};

type ChartTooltipProps = TooltipContentProps<TooltipValueType, number | string>;

const AllocationTooltip = ({ active, payload, label }: ChartTooltipProps) => {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <TooltipShell>
      <p className="font-semibold mb-1">{label}</p>
      {payload.map((entry) => (
        <SwatchRow
          key={entry.dataKey?.toString() ?? String(entry.name)}
          color={entry.color ?? "var(--text-muted)"}
          label={entry.dataKey === "atual" ? "Atual" : "Alvo"}
          value={`${Number(entry.value ?? 0).toFixed(1)}%`}
        />
      ))}
    </TooltipShell>
  );
};

export const AllocationVsTargetChart = ({
  portfolio,
}: {
  portfolio: PortfolioSummary;
}) => {
  const data: AllocationDatum[] = [
    {
      name: CLASS_NAMES.fixed_income,
      atual: portfolio.allocation.fixed_income_pct,
      alvo: portfolio.target_allocation.fixed_income,
    },
    {
      name: CLASS_NAMES.stocks,
      atual: portfolio.allocation.stocks_pct,
      alvo: portfolio.target_allocation.stocks,
    },
    {
      name: CLASS_NAMES.crypto,
      atual: portfolio.allocation.crypto_pct,
      alvo: portfolio.target_allocation.crypto,
    },
  ];

  return (
    <div className="space-y-3">
      <ChartLegend
        items={[
          { color: ACTUAL_COLOR, label: "Atual" },
          { color: TARGET_COLOR, label: "Alvo" },
        ]}
      />
      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barGap={2}>
            <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
            <XAxis
              dataKey="name"
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--border-strong)" }}
            />
            <YAxis
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              unit="%"
              width={44}
            />
            <Tooltip
              content={AllocationTooltip}
              cursor={{ fill: "var(--bg-secondary)", opacity: 0.5 }}
            />
            <Bar
              dataKey="atual"
              fill={ACTUAL_COLOR}
              radius={[4, 4, 0, 0]}
              maxBarSize={24}
              isAnimationActive={false}
            />
            <Bar
              dataKey="alvo"
              fill={TARGET_COLOR}
              radius={[4, 4, 0, 0]}
              maxBarSize={24}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

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
        Sem posições ainda — o donut aparece com a primeira compra.
      </p>
    );
  }

  return (
    <div className="flex items-center gap-8">
      <div style={{ width: 180, height: 180 }} className="shrink-0">
        <ResponsiveContainer>
          <PieChart>
            <Tooltip content={DonutTooltip} />
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius={54}
              outerRadius={84}
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
      <ul className="space-y-2.5 text-sm min-w-0">
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
              className="tabular text-xs w-24 text-right"
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
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(ts: number) =>
              new Date(ts).toLocaleDateString("pt-BR", {
                day: "2-digit",
                month: "short",
              })
            }
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: "var(--border-strong)" }}
            minTickGap={48}
          />
          <YAxis
            tickFormatter={compactBRL}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={72}
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
      {/* Clickable legend: toggles each series on/off. */}
      <div className="flex items-center gap-4 flex-wrap text-xs">
        {BENCH_SERIES.map((entry) => {
          const off = hidden[entry.key] === true;
          return (
            <button
              key={entry.key}
              type="button"
              onClick={() => toggle(entry.key)}
              aria-pressed={!off}
              title={off ? `Mostrar ${entry.label}` : `Ocultar ${entry.label}`}
              className="flex items-center gap-1.5 px-1.5 py-1 rounded-md transition-opacity"
              style={{ opacity: off ? 0.35 : 1 }}
            >
              <span
                className="inline-block w-3.5 rounded-full"
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
      <div style={{ width: "100%", height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="var(--border)" strokeWidth={1} vertical={false} />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(ts: number) =>
                new Date(ts).toLocaleDateString("pt-BR", {
                  day: "2-digit",
                  month: "short",
                })
              }
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--border-strong)" }}
              minTickGap={48}
            />
            <YAxis
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={48}
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
