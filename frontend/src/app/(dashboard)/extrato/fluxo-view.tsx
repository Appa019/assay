"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, ChevronDown, CreditCard, Repeat, WifiOff } from "lucide-react";
import { useForecast } from "@/hooks/use-forecast";
import type { ForecastLine, ForecastMonth } from "@/lib/api";
import { formatBRL, formatBRLCompact, parseLocalDate } from "@/lib/format";

const MONTH_ABBR = [
  "jan", "fev", "mar", "abr", "mai", "jun",
  "jul", "ago", "set", "out", "nov", "dez",
] as const;

const monthParts = (month: string): { label: string; year: string } => {
  const [year, index] = month.split("-").map(Number);
  return { label: MONTH_ABBR[index - 1], year: String(year).slice(2) };
};

const shortDate = (iso: string): string =>
  parseLocalDate(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

const originLabel = (line: ForecastLine): string => {
  if (line.origin === "recurring") return "todo mês";
  if (line.installment_no !== null && line.installment_count !== null) {
    return `parcela ${line.installment_no}/${line.installment_count}`;
  }
  return "lançado";
};

/**
 * One month's composition. Income first, then outflow, each line carrying the
 * day it moves — the answer to "por que esse mês aperta" has to be one tap
 * away or the number above is just a claim.
 */
const Composition = ({ month }: { month: ForecastMonth }) => {
  const income = month.lines.filter((line) => line.kind === "income");
  const expense = month.lines.filter((line) => line.kind === "expense");

  return (
    <div className="px-4 pb-5 pt-1">
      {[
        { rows: income, title: "Entra", tint: "var(--success)" },
        { rows: expense, title: "Sai", tint: "var(--accent)" },
      ]
        .filter((group) => group.rows.length > 0)
        .map((group) => (
          <div key={group.title} className="mt-4 first:mt-0">
            <p
              className="text-[10px] uppercase tracking-[0.18em]"
              style={{ color: "var(--text-muted)" }}
            >
              {group.title}
            </p>
            <ul className="mt-2 flex flex-col gap-2">
              {group.rows.map((line, index) => (
                <li
                  key={`${line.label}-${line.day}-${index}`}
                  className="flex items-baseline gap-3 text-[13px]"
                >
                  <span
                    className="w-7 shrink-0 tabular"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {String(line.day).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" style={{ color: "var(--text-primary)" }}>
                      {line.label}
                    </span>
                    <span
                      className="flex items-center gap-1 text-[11px]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {line.origin === "recurring" && (
                        <Repeat size={11} strokeWidth={2} aria-hidden />
                      )}
                      {originLabel(line)}
                      {line.card_name && ` · ${line.card_name}`}
                    </span>
                  </span>
                  <span
                    className="tabular shrink-0"
                    style={{
                      color:
                        line.origin === "recurring"
                          ? "var(--text-secondary)"
                          : "var(--text-primary)",
                    }}
                  >
                    {formatBRL(line.amount_brl)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}

      {month.invoices.length > 0 && (
        <div
          className="mt-4 flex flex-col gap-1.5 border-t pt-3"
          style={{ borderColor: "var(--border)" }}
        >
          {month.invoices.map((invoice) => (
            <p
              key={invoice.card_id}
              className="flex items-center gap-1.5 text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              <CreditCard size={12} strokeWidth={1.9} aria-hidden />
              Fatura {invoice.card_name} {formatBRL(invoice.total_brl)} vence{" "}
              {shortDate(invoice.due_on)} — já contada nas compras acima, não soma de novo.
            </p>
          ))}
        </div>
      )}
    </div>
  );
};

/**
 * A month on the ruler. Both bars are scaled against the largest figure of
 * the WHOLE horizon, never against their own month: that shared scale is what
 * makes the squeeze — and the relief when the last installment drops off —
 * legible by running your eye down the column.
 */
const MonthRow = ({
  month,
  scale,
  open,
  onToggle,
}: {
  month: ForecastMonth;
  scale: number;
  open: boolean;
  onToggle: () => void;
}) => {
  const { label, year } = monthParts(month.month);
  const width = (value: number) => `${scale > 0 ? (value / scale) * 100 : 0}%`;
  const negative = month.net_brl < 0;
  const empty = month.lines.length === 0;

  return (
    <li style={{ borderTop: "1px solid var(--border)" }}>
      <button
        type="button"
        onClick={onToggle}
        disabled={empty}
        aria-expanded={open}
        className="flex w-full items-center gap-4 px-4 py-4 text-left disabled:opacity-45"
      >
        <span className="w-11 shrink-0">
          <span
            className="block text-[15px] leading-none"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            {label}
          </span>
          <span className="mt-1 block text-[10px]" style={{ color: "var(--text-muted)" }}>
            {month.is_current ? "agora" : `/${year}`}
          </span>
        </span>

        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="flex h-2 items-center gap-2">
            <span
              className="h-2 rounded-full"
              style={{ width: width(month.income_brl), background: "var(--success)" }}
            />
            <span className="tabular text-[11px]" style={{ color: "var(--text-muted)" }}>
              {formatBRLCompact(month.income_brl)}
            </span>
          </span>
          <span className="flex h-2 items-center gap-2">
            <span
              className="h-2 rounded-full"
              style={{ width: width(month.expense_brl), background: "var(--accent)" }}
            />
            <span className="tabular text-[11px]" style={{ color: "var(--text-muted)" }}>
              {formatBRLCompact(month.expense_brl)}
            </span>
          </span>
        </span>

        <span className="flex shrink-0 items-center gap-1.5">
          <span
            className="tabular text-[15px] font-semibold"
            style={{ color: negative ? "var(--danger)" : "var(--text-primary)" }}
          >
            {formatBRLCompact(month.net_brl)}
          </span>
          {!empty && (
            <ChevronDown
              size={15}
              strokeWidth={1.8}
              aria-hidden
              className="transition-transform duration-200"
              style={{
                color: "var(--text-muted)",
                transform: open ? "rotate(180deg)" : "none",
              }}
            />
          )}
        </span>
      </button>

      {/* The month in progress is the only one where "already gone" and
          "still to go" differ — saying it here saves opening the row. */}
      {month.is_current && !empty && (
        <p className="-mt-2 px-4 pb-3 pl-[3.75rem] text-[11px]" style={{ color: "var(--text-muted)" }}>
          {formatBRL(month.realized_expense_brl)} já saíram ·{" "}
          {formatBRL(month.pending_expense_brl)} a sair
        </p>
      )}

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
            style={{ background: "var(--bg-secondary)" }}
          >
            <Composition month={month} />
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
};

/** Nothing registered yet: say what to do, not "sem dados". */
const EmptyState = () => (
  <div
    className="mt-8 rounded-lg border px-5 py-7"
    style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
  >
    <h3
      className="text-[1.15rem]"
      style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
    >
      Nada comprometido ainda
    </h3>
    <p className="mt-2 max-w-prose text-sm" style={{ color: "var(--text-secondary)" }}>
      O fluxo só mostra o que está registrado — salário, aluguel, assinatura,
      financiamento e as parcelas já lançadas. Conte para o consultor: “meu
      salário é 8.000 todo dia 5”, “aluguel 2.200 dia 10”.
    </p>
    <Link
      href="/consultor"
      className="mt-5 inline-flex min-h-[2.75rem] items-center gap-2 rounded-md px-4 text-sm font-semibold"
      style={{ background: "var(--accent)", color: "white" }}
    >
      Falar com o consultor
      <ArrowRight size={15} strokeWidth={2} />
    </Link>
  </div>
);

export const FluxoView = () => {
  const { forecast, error, loading } = useForecast(6);
  const [openMonth, setOpenMonth] = useState<string | null>(null);

  // One scale for the whole ruler — see MonthRow.
  const scale = useMemo(() => {
    if (!forecast) return 0;
    return Math.max(
      0,
      ...forecast.months.flatMap((month) => [month.income_brl, month.expense_brl]),
    );
  }, [forecast]);

  const horizon = forecast?.months.at(-1);
  const negative = (forecast?.total_net_brl ?? 0) < 0;

  if (loading && !forecast) {
    return (
      <div
        className="mt-6 h-72 animate-pulse rounded-lg"
        style={{ background: "var(--bg-secondary)" }}
      />
    );
  }

  return (
    <div>
      {error && (
        <div
          className="mb-6 flex items-start gap-3 rounded-lg border p-4 text-sm"
          style={{
            borderColor: "var(--danger)",
            background: "var(--danger-light)",
            color: "var(--text-primary)",
          }}
        >
          <WifiOff size={17} strokeWidth={1.9} className="mt-0.5 shrink-0" />
          <span>Backend fora do ar. O fluxo abaixo não é real.</span>
        </div>
      )}

      {forecast && !forecast.has_commitments && <EmptyState />}

      {forecast && forecast.has_commitments && (
        <>
          <section>
            <p
              className="text-[11px] uppercase tracking-[0.18em]"
              style={{ color: "var(--text-muted)" }}
            >
              Sobra prevista {horizon && `até ${monthParts(horizon.month).label}/${monthParts(horizon.month).year}`}
            </p>
            <p
              className="mt-1.5 text-[2.4rem] leading-none md:text-[2.8rem]"
              style={{
                fontFamily: "var(--font-heading)",
                color: negative ? "var(--danger)" : "var(--text-primary)",
              }}
            >
              {formatBRL(forecast.total_net_brl)}
            </p>
            <p className="mt-3 max-w-prose text-[13px]" style={{ color: "var(--text-secondary)" }}>
              {formatBRL(forecast.total_income_brl)} previstos de entrada contra{" "}
              {formatBRL(forecast.total_expense_brl)} de saída em 6 meses. Só conta o
              que está cadastrado — mercado, delivery e o resto do variável ficam
              de fora, então trate como teto, não como expectativa.
            </p>
          </section>

          <section className="mt-8">
            <div
              className="flex items-center gap-4 text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2 w-4 rounded-full"
                  style={{ background: "var(--success)" }}
                  aria-hidden
                />
                entra
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2 w-4 rounded-full"
                  style={{ background: "var(--accent)" }}
                  aria-hidden
                />
                sai
              </span>
            </div>

            <ul
              className="mt-3 overflow-hidden rounded-lg border"
              style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
            >
              {forecast.months.map((month) => (
                <MonthRow
                  key={month.month}
                  month={month}
                  scale={scale}
                  open={openMonth === month.month}
                  onToggle={() =>
                    setOpenMonth(openMonth === month.month ? null : month.month)
                  }
                />
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
};
