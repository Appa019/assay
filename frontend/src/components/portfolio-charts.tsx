"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from "recharts";
import type { PortfolioHistoryPoint, PortfolioSummary } from "@/lib/api";
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
