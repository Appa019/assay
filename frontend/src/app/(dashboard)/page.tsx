"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, RefreshCw, WifiOff } from "lucide-react";
import {
  currentMonth,
  fetchBenchmark,
  fetchCashflowSummary,
  fetchOrders,
  type BenchmarkResponse,
  type CashflowSummary,
  type Order,
} from "@/lib/api";
import { usePortfolio } from "@/hooks/use-portfolio";
import { useCadence } from "@/hooks/use-cadence";
import { useMacro } from "@/hooks/use-macro";
import { usePortfolioHistory } from "@/hooks/use-portfolio-history";
import { useCards } from "@/hooks/use-cards";
import { formatBRL, formatBRLCompact, parseLocalDate } from "@/lib/format";
import { OrdersPanel } from "@/components/orders-panel";
import {
  AllocationDonut,
  BenchmarkChart,
  EquityCurveChart,
} from "@/components/portfolio-charts";
import {
  CategoryBars,
  FlowRails,
  MandateRails,
  type CategorySlice,
} from "@/components/overview-charts";

const DATE_LINE = new Intl.DateTimeFormat("pt-BR", {
  weekday: "long",
  day: "numeric",
  month: "long",
});
const MONTH_NAME = new Intl.DateTimeFormat("pt-BR", { month: "long" });
const CLOCK = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
});

/** Beyond this the tail folds into one row instead of growing the list. */
const MAX_CATEGORIES = 6;

/** "2026-07" → "julho". */
const monthName = (month: string): string => {
  const [year, index] = month.split("-").map(Number);
  return MONTH_NAME.format(new Date(year, index - 1, 1));
};

const cadenceLabel = (days: number | null): string => {
  if (days === null) return "nenhum aporte ainda";
  if (days === 0) return "último aporte hoje";
  if (days === 1) return "último aporte ontem";
  return `último aporte há ${days} dias`;
};

/** The standard 0–100 crypto sentiment bands, named in pt-BR. */
const fearGreedLabel = (value: number): string => {
  if (value < 25) return "medo extremo";
  if (value < 45) return "medo";
  if (value <= 55) return "neutro";
  if (value <= 75) return "ganância";
  return "ganância extrema";
};

const num = (
  value: number | null | undefined,
  suffix = "",
  prefix = "",
  digits = 2,
  minDigits = 0
): string => {
  if (value === null || value === undefined) return "–";
  return `${prefix}${value.toLocaleString("pt-BR", {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: digits,
  })}${suffix}`;
};

const DashboardPage = () => {
  const { data: portfolio, loading: pLoading, error: pError, refresh } = usePortfolio();
  const { data: cadence } = useCadence();
  const { data: macro, loading: macroLoading } = useMacro();
  const { data: history } = usePortfolioHistory(365);
  const [benchmark, setBenchmark] = useState<BenchmarkResponse | null>(null);
  const [pendingOrders, setPendingOrders] = useState<Order[] | null>(null);
  const [cashflow, setCashflow] = useState<CashflowSummary | null>(null);
  const [cashflowFailed, setCashflowFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const month = currentMonth();
  // The page is prerendered at build time, and suppressHydrationWarning KEEPS
  // the prerendered text: the date line read "14 de setembro" on 19/10. Dates
  // are rendered only once the browser has mounted.
  const [today, setToday] = useState<Date | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setToday(new Date()), 0);
    return () => clearTimeout(timer);
  }, []);

  const loadPendingOrders = useCallback(async () => {
    try {
      setPendingOrders(await fetchOrders("pending"));
    } catch {
      // Network error: hide the block instead of breaking the dashboard.
      setPendingOrders(null);
    }
  }, []);

  const loadBenchmark = useCallback(async () => {
    try {
      setBenchmark(await fetchBenchmark(365));
    } catch {
      setBenchmark(null);
    }
  }, []);

  const loadCashflow = useCallback(async () => {
    try {
      setCashflow(await fetchCashflowSummary(month));
      setCashflowFailed(false);
    } catch {
      // Kept apart from "no entries": a zero here would be a lie.
      setCashflow(null);
      setCashflowFailed(true);
    }
  }, [month]);

  useEffect(() => {
    // Defer to a task so no state update runs synchronously in the effect.
    const timer = setTimeout(() => {
      void loadPendingOrders();
      void loadBenchmark();
      void loadCashflow();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadPendingOrders, loadBenchmark, loadCashflow]);

  const reloadAll = async () => {
    setRefreshing(true);
    await Promise.all([
      refresh(),
      loadPendingOrders(),
      loadBenchmark(),
      loadCashflow(),
    ]);
    setRefreshing(false);
  };

  const backendDown = !pLoading && !portfolio && pError !== null;
  // The hook keeps the last good payload when a refresh fails, so the figures
  // stay on screen. Say that they are old rather than let them pass as fresh.
  const stale = !pLoading && portfolio !== null && pError !== null;
  const invested = portfolio !== null && portfolio.total_value > 0;
  const hasBenchmark = benchmark !== null && benchmark.series.length > 0;
  const hasCurve = history !== null && history.length >= 2;
  const hasOrders = pendingOrders !== null && pendingOrders.length > 0;

  // Ranked spending, with the tail folded so the list never outgrows the card.
  const expenseSlices: CategorySlice[] = useMemo(() => {
    const expenses = (cashflow?.by_category ?? [])
      .filter((entry) => entry.kind === "expense")
      .sort((a, b) => b.total_brl - a.total_brl);
    if (expenses.length <= MAX_CATEGORIES) return expenses;
    const head = expenses.slice(0, MAX_CATEGORIES - 1);
    const tail = expenses.slice(MAX_CATEGORIES - 1);
    return [
      ...head,
      {
        category: `outras ${tail.length} categorias`,
        total_brl: tail.reduce((sum, entry) => sum + entry.total_brl, 0),
      },
    ];
  }, [cashflow]);

  const netColor =
    cashflow === null || cashflow.net_brl === 0
      ? "var(--text-primary)"
      : cashflow.net_brl > 0
        ? "var(--success)"
        : "var(--danger)";

  const { cards } = useCards();
  // The soonest bill: a closed invoice waiting for its due date, else the
  // open one. ISO dates sort chronologically as strings.
  const nextDue = useMemo(() => {
    if (!cards || cards.length === 0) return null;
    const dues = cards.map((card) => {
      const closed = card.last_closed_invoice;
      return closed && closed.status === "closed" ? closed.due_on : card.open_invoice.due_on;
    });
    return [...dues].sort()[0] ?? null;
  }, [cards]);
  const nextDueLabel =
    nextDue === null
      ? null
      : parseLocalDate(nextDue).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

  return (
    <div className="max-w-6xl">
      {/* pr reserves room for the floating eye + bell on mobile (~6.75rem
          from the right edge) so "Atualizar" wraps left of them instead of
          sitting underneath. */}
      <header className="flex items-center justify-between gap-4 pr-[6.75rem] md:pr-0">
        <div className="min-w-0">
          <h1 className="sr-only">Visão geral</h1>
          <p
            className="truncate text-[11px] font-medium uppercase tracking-[0.18em]"
            style={{ color: "var(--text-muted)" }}
          >
            {today ? DATE_LINE.format(today) : "\u00a0"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reloadAll()}
          disabled={refreshing}
          className="flex min-h-11 shrink-0 items-center gap-2 rounded-md border px-3.5 text-[13px] font-medium disabled:opacity-60"
          style={{
            background: "var(--bg-card)",
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : undefined} />
          Atualizar
        </button>
      </header>

      {backendDown && (
        <section
          className="mt-4 flex flex-col gap-4 rounded-md p-5 md:flex-row md:items-center md:justify-between md:p-6"
          style={{ background: "var(--danger-light)", border: "1px solid var(--danger)" }}
        >
          <div className="flex items-start gap-3">
            <WifiOff size={18} style={{ color: "var(--danger)" }} className="mt-0.5 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Backend indisponível
              </p>
              <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                Nada nesta tela está atualizado. Verifique se o backend está
                rodando (<code>./start.sh</code>).
              </p>
              <p className="mt-1.5 break-words text-[11px]" style={{ color: "var(--text-muted)" }}>
                {pError}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void reloadAll()}
            className="flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold"
            style={{ background: "var(--accent)", color: "white" }}
          >
            <RefreshCw size={13} />
            Tentar de novo
          </button>
        </section>
      )}

      {stale && (
        <p className="mt-4 text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          A última atualização falhou ({pError}): os números abaixo são os da
          leitura anterior.
        </p>
      )}

      {/* The two figures the owner opens the app for, side by side and louder
          than anything else. Everything below is the detail behind them. */}
      <section
        className="mt-4 rounded-md border md:mt-5"
        style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
      >
        <div className="grid md:grid-cols-2">
          <div className="px-5 py-6 md:px-8 md:py-9">
            <Eyebrow>Patrimônio</Eyebrow>
            {backendDown ? (
              <>
                <HeroFigure value="–" color="var(--text-muted)" />
                <HeroNote>Sem conexão com o backend.</HeroNote>
              </>
            ) : portfolio === null ? (
              <HeroSkeleton />
            ) : (
              <>
                <HeroFigure
                  value={formatBRLCompact(portfolio.total_value)}
                  color="var(--text-primary)"
                />
                {portfolio.assets.length === 0 ? (
                  <HeroNote action={{ href: "/investimentos?aba=aportar", label: "Registrar aporte" }}>
                    Nenhuma posição ainda.
                  </HeroNote>
                ) : (
                  <HeroNote>
                    {portfolio.assets.length} lote
                    {portfolio.assets.length > 1 ? "s" : ""}
                    {cadence ? ` · ${cadenceLabel(cadence.days_since_last)}` : ""}
                  </HeroNote>
                )}
              </>
            )}
          </div>

          <div
            className="border-t px-5 py-6 md:border-t-0 md:border-l md:px-8 md:py-9"
            style={{ borderColor: "var(--border)" }}
          >
            <Eyebrow>
              Saldo de <span>{today ? monthName(month) : "\u00a0"}</span>
            </Eyebrow>
            {cashflowFailed ? (
              <>
                <HeroFigure value="–" color="var(--text-muted)" />
                <HeroNote>Não foi possível carregar o mês.</HeroNote>
              </>
            ) : cashflow === null ? (
              <HeroSkeleton />
            ) : (
              <>
                {/* Compact like the figure beside it; the exact cents live one
                    glance below, in the month's rails. */}
                <HeroFigure value={formatBRLCompact(cashflow.net_brl)} color={netColor} />
                {cashflow.entries === 0 ? (
                  <HeroNote action={{ href: "/consultor", label: "Registrar gasto" }}>
                    Nenhum lançamento neste mês.
                  </HeroNote>
                ) : (
                  <HeroNote>
                    {cashflow.entries} lançamento{cashflow.entries > 1 ? "s" : ""}
                  </HeroNote>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {/* ── O mês ─────────────────────────────────────────────────── */}
      <section className="mt-10 md:mt-14">
        <SectionHead
          title="O mês"
          action={{ href: "/consultor", label: "Consultor" }}
        />
        <div
          className="mt-3 rounded-md border p-5 md:p-7"
          style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
        >
          {cashflowFailed ? (
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Os lançamentos do mês não carregaram.
              </p>
              <button
                type="button"
                onClick={() => void loadCashflow()}
                className="flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 text-[13px] font-medium md:shrink-0"
                style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
              >
                <RefreshCw size={13} />
                Tentar de novo
              </button>
            </div>
          ) : cashflow === null ? (
            <BarSkeleton rows={2} />
          ) : cashflow.entries === 0 ? (
            // The fact is already stated above, under the month's figure;
            // repeating it here would only cost a line.
            <div>
              <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                Conte um gasto ao consultor em uma frase, ou mande a foto do
                cupom, que ele lê, classifica e lança.
              </p>
              <Link
                href="/consultor"
                className="mt-4 flex min-h-11 w-full items-center justify-center gap-2 rounded-md px-5 text-sm font-semibold md:w-auto md:self-start"
                style={{ background: "var(--accent)", color: "white" }}
              >
                Abrir o consultor
                <ArrowRight size={14} />
              </Link>
            </div>
          ) : (
            <div className="grid gap-7 md:grid-cols-2 md:gap-12">
              {/* Two rails against a longer category list: centering keeps the
                  short column from leaving a hole under itself. */}
              <div className="md:self-center">
                <FlowRails
                  income={cashflow.income_brl}
                  expense={cashflow.expense_brl}
                />
                {cashflow.card_expense_brl > 0 && nextDueLabel && (
                  <p className="tabular mt-4 text-[12px]" style={{ color: "var(--text-muted)" }}>
                    No cartão {formatBRL(cashflow.card_expense_brl)} · fatura vence {nextDueLabel}
                  </p>
                )}
              </div>
              <div>
                <p
                  className="text-[11px] font-medium uppercase tracking-[0.16em]"
                  style={{ color: "var(--text-muted)" }}
                >
                  Para onde foi
                </p>
                <div className="mt-3.5">
                  {expenseSlices.length > 0 ? (
                    <CategoryBars slices={expenseSlices} />
                  ) : (
                    <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                      Nenhum gasto registrado, só entradas.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── Ordens pendentes ──────────────────────────────────────── */}
      {!backendDown && hasOrders && pendingOrders && (
        <section className="mt-10 md:mt-14">
          <OrdersPanel
            orders={pendingOrders}
            title="Ordens pendentes"
            subtitle="Folha do comitê aguardando execução: registre o que você executou ou pule"
            onChanged={loadPendingOrders}
          />
        </section>
      )}

      {/* ── Carteira ──────────────────────────────────────────────── */}
      {!backendDown && portfolio && (
        <section className="mt-10 md:mt-14">
          <SectionHead
            title="Carteira"
            action={{ href: "/investimentos", label: "Investimentos" }}
          />

          {!invested ? (
            // Empty carteira: show the mandate the first contribution will be
            // split into, not another "you have nothing" line.
            <Panel className="mt-3">
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Sem posições. O mandato divide o primeiro aporte assim:
              </p>
              <div className="mt-5 max-w-md">
                <MandateRails portfolio={portfolio} />
              </div>
            </Panel>
          ) : (
            <div className="mt-3 space-y-4">
              {hasCurve && history ? (
                <Panel title="Curva de patrimônio" sub="Valor total nos snapshots diários">
                  <EquityCurveChart history={history} />
                </Panel>
              ) : (
                <Panel>
                  <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                    A curva de patrimônio começa no segundo snapshot diário.
                  </p>
                </Panel>
              )}

              <div className="grid gap-4 lg:grid-cols-5">
                <Panel
                  className="lg:col-span-3"
                  title="Composição"
                  sub="Quanto há em cada classe, em R$"
                >
                  <AllocationDonut portfolio={portfolio} />
                </Panel>
                <Panel
                  className="lg:col-span-2"
                  title="Distância do alvo"
                  sub="Percentual atual contra a meta do mandato"
                >
                  <MandateRails portfolio={portfolio} />
                </Panel>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Desempenho ────────────────────────────────────────────── */}
      {!backendDown && invested && (
        <section className="mt-8 md:mt-12">
          <SectionHead title="Desempenho" />
          {hasBenchmark && benchmark ? (
            <Panel
              className="mt-3"
              title="Carteira vs CDI, Ibovespa e BTC"
              sub="Retorno acumulado (TWR, base 100) · toque na legenda para ocultar uma série"
            >
              <BenchmarkChart series={benchmark.series} />
            </Panel>
          ) : (
            <Panel className="mt-3">
              <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                {benchmark?.note ??
                  "A comparação com CDI, Ibovespa e BTC aparece quando houver série suficiente."}
              </p>
            </Panel>
          )}
        </section>
      )}

      {/* ── Macro ─────────────────────────────────────────────────── */}
      {!backendDown && (
        <section className="mt-12 md:mt-16">
          <div className="flex items-baseline justify-between gap-3">
            <Eyebrow>Macro de hoje</Eyebrow>
            {macro && (
              <span className="tabular text-[11px]" style={{ color: "var(--text-muted)" }}>
                {CLOCK.format(parseLocalDate(macro.captured_at))}
              </span>
            )}
          </div>

          {macro ? (
            <div
              className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border md:grid-cols-4"
              style={{ background: "var(--border)", borderColor: "var(--border)" }}
            >
              <MacroCell label="Selic" value={num(macro.macro.selic, "%")} />
              <MacroCell label="CDI" value={num(macro.macro.cdi, "%")} />
              <MacroCell label="IPCA 12m" value={num(macro.macro.ipca_12m, "%")} />
              <MacroCell label="USD/BRL" value={num(macro.macro.usd_brl, "", "R$ ", 2, 2)} />
              <MacroCell
                label="Ibovespa"
                value={num(macro.ibovespa.level, " pts", "", 0)}
                delta={macro.ibovespa.day_change_pct}
              />
              <MacroCell
                label="Dominância BTC"
                value={num(macro.crypto_global.btc_dominance, "%", "", 1)}
              />
              <MacroCell
                span
                label="Fear & Greed"
                value={macro.fear_greed_index?.toString() ?? "–"}
                note={
                  macro.fear_greed_index === null
                    ? undefined
                    : fearGreedLabel(macro.fear_greed_index)
                }
              />
            </div>
          ) : macroLoading ? (
            <div
              className="mt-3 h-32 animate-pulse rounded-md"
              style={{ background: "var(--bg-secondary)" }}
            />
          ) : (
            <p className="mt-3 text-[13px]" style={{ color: "var(--text-secondary)" }}>
              Não foi possível capturar os indicadores agora.
            </p>
          )}
        </section>
      )}

    </div>
  );
};

/* ── Building blocks ───────────────────────────────────────────────── */

const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <p
    className="text-[11px] font-medium uppercase tracking-[0.18em]"
    style={{ color: "var(--text-muted)" }}
  >
    {children}
  </p>
);

const SectionHead = ({
  title,
  action,
}: {
  title: string;
  action?: { href: string; label: string };
}) => (
  <div className="flex items-center justify-between gap-3">
    <Eyebrow>{title}</Eyebrow>
    {action && (
      // Negative margin keeps the row tight while the hit area clears 44px.
      <Link
        href={action.href}
        className="-my-3 flex min-h-11 items-center gap-1 text-[13px] font-medium"
        style={{ color: "var(--accent-strong)" }}
      >
        {action.label}
        <ArrowRight size={13} />
      </Link>
    )}
  </div>
);

const HeroFigure = ({ value, color }: { value: string; color: string }) => (
  <motion.p
    // Re-keyed on the value so a refresh reads as the number changing.
    key={value}
    initial={{ opacity: 0, y: 4 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.2, ease: "easeOut" }}
    className="tabular mt-2 leading-[0.95]"
    style={{
      fontFamily: "var(--font-heading)",
      fontSize: "clamp(2.15rem, 9vw, 3.25rem)",
      color,
    }}
  >
    {value}
  </motion.p>
);

const HeroSkeleton = () => (
  <>
    <div
      className="mt-2 h-[2.6rem] w-44 animate-pulse rounded md:h-[3.1rem]"
      style={{ background: "var(--bg-secondary)" }}
    />
    <div
      className="mt-3 h-3 w-28 animate-pulse rounded"
      style={{ background: "var(--bg-secondary)" }}
    />
  </>
);

const BarSkeleton = ({ rows }: { rows: number }) => (
  <div className="space-y-5">
    {Array.from({ length: rows }, (_, index) => (
      <div key={index} className="space-y-2">
        <div
          className="h-3 w-24 animate-pulse rounded"
          style={{ background: "var(--bg-secondary)" }}
        />
        <div
          className="h-2.5 animate-pulse rounded"
          style={{ background: "var(--bg-secondary)" }}
        />
      </div>
    ))}
  </div>
);

const HeroNote = ({
  children,
  action,
}: {
  children: React.ReactNode;
  action?: { href: string; label: string };
}) => (
  <div className="mt-2.5">
    <p className="text-[13px]" style={{ color: "var(--text-muted)" }}>
      {children}
    </p>
    {action && (
      <Link
        href={action.href}
        className="-my-2.5 flex min-h-11 items-center gap-1 text-[13px] font-medium"
        style={{ color: "var(--accent-strong)" }}
      >
        {action.label}
        <ArrowRight size={13} />
      </Link>
    )}
  </div>
);

const Panel = ({
  title,
  sub,
  className = "",
  children,
}: {
  title?: string;
  sub?: string;
  className?: string;
  children: React.ReactNode;
}) => (
  <div
    className={`rounded-md border p-5 md:p-6 ${className}`}
    style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
  >
    {title && (
      <h2
        className="text-xl tracking-tight md:text-2xl"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        {title}
      </h2>
    )}
    {sub && (
      <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
        {sub}
      </p>
    )}
    <div className={title || sub ? "mt-5" : ""}>{children}</div>
  </div>
);

const MacroCell = ({
  label,
  value,
  delta,
  note,
  span = false,
}: {
  label: string;
  value: string;
  delta?: number | null;
  note?: string;
  span?: boolean;
}) => (
  <div
    className={`px-4 py-3.5 ${span ? "col-span-2" : ""}`}
    style={{ background: "var(--bg-primary)" }}
  >
    <p
      className="text-[10px] font-medium uppercase tracking-[0.16em]"
      style={{ color: "var(--text-muted)" }}
    >
      {label}
    </p>
    <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
      <span
        className="tabular text-[15px] font-semibold"
        style={{ color: "var(--text-primary)" }}
      >
        {value}
      </span>
      {delta !== null && delta !== undefined && (
        <span
          className="tabular text-[12px] font-medium"
          style={{ color: delta >= 0 ? "var(--success)" : "var(--danger)" }}
        >
          {`${delta >= 0 ? "+" : ""}${num(delta, "%", "", 2, 2)}`}
        </span>
      )}
      {note && (
        <span className="text-[12px]" style={{ color: "var(--text-secondary)" }}>
          {note}
        </span>
      )}
    </p>
  </div>
);

export default DashboardPage;
