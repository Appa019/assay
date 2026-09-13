"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Trash2,
  WifiOff,
} from "lucide-react";
import { useCashflow } from "@/hooks/use-cashflow";
import {
  currentMonth,
  deleteCashflowEntry,
  deleteCashflowGroup,
  type CashflowEntry,
  type CategoryTotal,
  type CreditCard,
} from "@/lib/api";
import { useCards } from "@/hooks/use-cards";
import { formatAmount, formatBRL, parseLocalDate } from "@/lib/format";

const MONTH_NAMES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
] as const;

const shiftMonth = (month: string, delta: number): string => {
  const [year, m] = month.split("-").map(Number);
  const date = new Date(year, m - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
};

const monthLabel = (month: string): string => {
  const [year, m] = month.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} de ${year}`;
};

const dayLabel = (iso: string): string => {
  const date = parseLocalDate(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - date.getTime()) / 86_400_000);
  if (diff === 0) return "hoje";
  if (diff === 1) return "ontem";
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
};

const shortDate = (iso: string): string =>
  parseLocalDate(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

const daysUntil = (iso: string): number => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.max(0, Math.round((parseLocalDate(iso).getTime() - today.getTime()) / 86_400_000));
};

const sourceLabel = (source: CashflowEntry["source"]): string =>
  source === "chat" ? "consultor" : source === "bot" ? "comando no Telegram" : "site";

/** Ranked bars for one side of the ledger, scaled against their own largest. */
const CategoryBars = ({
  title,
  rows,
  tint,
}: {
  title: string;
  rows: CategoryTotal[];
  tint: string;
}) => {
  const top = rows[0]?.total_brl ?? 0;
  return (
    <section className="mt-9">
      <h3
        className="text-[11px] uppercase tracking-[0.18em]"
        style={{ color: "var(--text-muted)" }}
      >
        {title}
      </h3>
      <div className="mt-3.5 flex flex-col gap-3">
        {rows.slice(0, 8).map((row) => (
          <div key={`${row.kind}-${row.category}`}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate capitalize" style={{ color: "var(--text-primary)" }}>
                {row.category}
              </span>
              <span className="tabular shrink-0" style={{ color: "var(--text-secondary)" }}>
                {formatBRL(row.total_brl)}
              </span>
            </div>
            <div
              className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full"
              style={{ background: "var(--bg-secondary)" }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${top > 0 ? (row.total_brl / top) * 100 : 0}%`,
                  background: tint,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

/** The open invoice per card, plus the last closed one while it waits to be paid. */
const InvoiceBlock = ({ cards }: { cards: CreditCard[] }) => (
  <section className="mt-9">
    <h3
      className="text-[11px] uppercase tracking-[0.18em]"
      style={{ color: "var(--text-muted)" }}
    >
      Cartão
    </h3>
    <div className="mt-3.5 flex flex-col gap-3">
      {cards.map((card) => {
        const open = card.open_invoice;
        const closed = card.last_closed_invoice;
        const days = daysUntil(open.closes_on);
        return (
          <div
            key={card.id}
            className="rounded-lg border px-4 py-4"
            style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
          >
            <div className="flex items-baseline justify-between gap-3">
              <p
                className="text-[12px] font-semibold uppercase tracking-[0.1em]"
                style={{ color: "var(--text-secondary)" }}
              >
                {card.name}
              </p>
              <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                fatura aberta
              </p>
            </div>
            <p
              className="tabular mt-1 text-[1.75rem] leading-none"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              {formatBRL(open.total_brl)}
            </p>
            <p className="mt-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
              fecha {shortDate(open.closes_on)} ({days === 0 ? "hoje" : `${days} dias`}) · vence{" "}
              {shortDate(open.due_on)}
            </p>
            {closed && (
              <p
                className="mt-3 border-t pt-3 text-[13px]"
                style={{
                  borderColor: "var(--border)",
                  color: closed.status === "past" ? "var(--text-muted)" : "var(--text-primary)",
                }}
              >
                {closed.status === "past"
                  ? `Última fatura ${formatBRL(closed.total_brl)}, venceu ${shortDate(closed.due_on)}`
                  : `Fatura fechada · ${formatBRL(closed.total_brl)} · vence ${shortDate(closed.due_on)}`}
              </p>
            )}
          </div>
        );
      })}
    </div>
  </section>
);

/**
 * Read-only statement. Entries are created by talking to the consultant, so
 * this screen never asks for input — only deletion survives (one row, or a
 * whole installment purchase), because a misclassified line needs a one-tap
 * correction, not a round trip.
 */
const ExtratoPage = () => {
  const [month, setMonth] = useState(currentMonth());
  const { entries, summary, loading, error, refresh } = useCashflow(month);
  const { cards } = useCards();
  const [openId, setOpenId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const isCurrent = month === currentMonth();

  const byDay = useMemo(() => {
    const groups = new Map<string, CashflowEntry[]>();
    for (const entry of entries ?? []) {
      const list = groups.get(entry.occurred_on) ?? [];
      list.push(entry);
      groups.set(entry.occurred_on, list);
    }
    return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [entries]);

  const expenses = useMemo(
    () =>
      (summary?.by_category ?? [])
        .filter((c) => c.kind === "expense")
        .sort((a, b) => b.total_brl - a.total_brl),
    [summary],
  );
  const incomes = useMemo(
    () =>
      (summary?.by_category ?? [])
        .filter((c) => c.kind === "income")
        .sort((a, b) => b.total_brl - a.total_brl),
    [summary],
  );
  const benefitWallets = useMemo(
    () => (summary?.by_wallet ?? []).filter((w) => w.wallet !== "conta"),
    [summary],
  );

  const remove = async (id: string) => {
    setOpenId(null);
    setDeleteError(null);
    try {
      await deleteCashflowEntry(id);
      refresh();
    } catch {
      setDeleteError("Não foi possível excluir o lançamento.");
    }
  };

  const removeGroup = async (groupId: string) => {
    setOpenId(null);
    setDeleteError(null);
    try {
      await deleteCashflowGroup(groupId);
      refresh();
    } catch {
      setDeleteError("Não foi possível excluir a compra parcelada.");
    }
  };

  const cardExpense = summary?.card_expense_brl ?? 0;

  const net = summary?.net_brl ?? 0;
  const netColor =
    net > 0 ? "var(--success)" : net < 0 ? "var(--danger)" : "var(--text-secondary)";

  return (
    <div className="max-w-3xl pb-4">
      {/* pr reserves room for the floating eye + bell on mobile (~6.75rem
          from the right edge) so the month arrows wrap left of them instead
          of sitting underneath. */}
      <header className="flex items-center justify-between gap-3 pr-[6.75rem] md:pr-0">
        <div className="min-w-0">
          <p
            className="text-[11px] uppercase tracking-[0.18em]"
            style={{ color: "var(--text-muted)" }}
          >
            Extrato
          </p>
          <h2
            className="truncate text-[1.7rem] leading-tight first-letter:uppercase md:text-3xl"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            {monthLabel(month)}
          </h2>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setMonth(shiftMonth(month, -1))}
            aria-label="Mês anterior"
            className="grid h-11 w-11 place-items-center rounded-md border"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={18} strokeWidth={1.9} />
          </button>
          <button
            type="button"
            onClick={() => setMonth(shiftMonth(month, 1))}
            disabled={isCurrent}
            aria-label="Próximo mês"
            className="grid h-11 w-11 place-items-center rounded-md border disabled:opacity-35"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            <ChevronRight size={18} strokeWidth={1.9} />
          </button>
        </div>
      </header>

      {error && (
        <div
          className="mt-6 flex items-start gap-3 rounded-lg border p-4 text-sm"
          style={{
            borderColor: "var(--danger)",
            background: "var(--danger-light)",
            color: "var(--text-primary)",
          }}
        >
          <WifiOff size={17} strokeWidth={1.9} className="mt-0.5 shrink-0" />
          <span>Backend fora do ar. Os valores abaixo não são reais.</span>
        </div>
      )}

      <section className="mt-7">
        <p
          className="text-[11px] uppercase tracking-[0.18em]"
          style={{ color: "var(--text-muted)" }}
        >
          Saldo do mês
        </p>
        <p
          className="tabular mt-1 leading-none"
          style={{
            fontFamily: "var(--font-heading)",
            fontSize: "clamp(2.25rem, 11vw, 3.5rem)",
            color: netColor,
          }}
        >
          {loading && !summary ? "–" : formatBRL(net)}
        </p>

        <div
          className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg border"
          style={{ borderColor: "var(--border)", background: "var(--border)" }}
        >
          {(
            [
              { label: "Entrou", value: summary?.income_brl ?? 0, color: "var(--success)" },
              { label: "Saiu", value: summary?.expense_brl ?? 0, color: "var(--danger)" },
            ] as const
          ).map(({ label, value, color }) => (
            <div key={label} className="px-4 py-3.5" style={{ background: "var(--bg-card)" }}>
              <p
                className="text-[10px] uppercase tracking-[0.16em]"
                style={{ color: "var(--text-muted)" }}
              >
                {label}
              </p>
              <p className="tabular mt-1 text-lg font-semibold" style={{ color }}>
                {formatBRL(value)}
              </p>
            </div>
          ))}
        </div>

        {benefitWallets.length > 0 && (
          <div
            className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12px]"
            style={{ color: "var(--text-muted)" }}
          >
            {benefitWallets.map((w) => (
              <span key={w.wallet} className="tabular">
                <span className="font-semibold uppercase tracking-[0.08em]">{w.wallet}</span>
                {` entrou ${formatBRL(w.income_brl)} · saiu ${formatBRL(w.expense_brl)}`}
              </span>
            ))}
          </div>
        )}

        {cardExpense > 0 && (
          <p className="tabular mt-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
            no cartão {formatBRL(cardExpense)}
          </p>
        )}
      </section>

      {cards && cards.length > 0 && <InvoiceBlock cards={cards} />}
      {cards && cards.length === 0 && (
        <p className="mt-6 text-[13px]" style={{ color: "var(--text-muted)" }}>
          <Link href="/configuracoes" className="underline underline-offset-4">
            Cadastre seu cartão em Ajustes
          </Link>{" "}
          para acompanhar a fatura aqui.
        </p>
      )}

      {expenses.length > 0 && (
        <CategoryBars title="Para onde foi" rows={expenses} tint="var(--accent)" />
      )}
      {incomes.length > 0 && (
        <CategoryBars title="De onde veio" rows={incomes} tint="var(--success)" />
      )}

      <section className="mt-9">
        <h3
          className="text-[11px] uppercase tracking-[0.18em]"
          style={{ color: "var(--text-muted)" }}
        >
          Lançamentos
        </h3>

        {deleteError && (
          <p className="mt-2 text-[13px]" style={{ color: "var(--danger)" }}>
            {deleteError}
          </p>
        )}

        {loading && !entries && (
          <div className="mt-3.5 flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-14 animate-pulse rounded-lg"
                style={{ background: "var(--bg-secondary)" }}
              />
            ))}
          </div>
        )}

        {entries && entries.length === 0 && (
          <div
            className="mt-3.5 rounded-lg border p-5"
            style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
          >
            <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              Nada em {monthLabel(month)}. Conte ao consultor o que você gastou ou
              recebeu, em uma frase ou mandando a foto do cupom, e aparece aqui.
            </p>
            <Link
              href="/consultor"
              className="mt-4 flex min-h-[2.75rem] w-full items-center justify-center gap-2 rounded-md text-sm font-semibold sm:w-auto sm:px-6"
              style={{ background: "var(--accent)", color: "white" }}
            >
              Abrir o consultor
              <ArrowRight size={15} />
            </Link>
          </div>
        )}

        {byDay.map(([day, dayEntries]) => (
          <div key={day} className="mt-5">
            <p
              className="text-[11px] font-medium uppercase tracking-[0.14em]"
              style={{ color: "var(--text-muted)" }}
            >
              {dayLabel(day)}
            </p>

            <ul
              className="mt-2 overflow-hidden rounded-lg border"
              style={{ borderColor: "var(--border)" }}
            >
              {dayEntries.map((entry, index) => {
                const income = entry.kind === "income";
                const open = openId === entry.id;
                const group = entry.installment_group;
                return (
                  <li
                    key={entry.id}
                    style={{
                      background: "var(--bg-card)",
                      borderTop: index === 0 ? "none" : "1px solid var(--border)",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => setOpenId(open ? null : entry.id)}
                      aria-expanded={open}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left"
                    >
                      <span className="min-w-0 flex-1">
                        <span
                          className="block truncate text-[15px]"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {entry.description || entry.category}
                        </span>
                        <span
                          className="block text-[12px] capitalize"
                          style={{ color: "var(--text-muted)" }}
                        >
                          {entry.category}
                          {entry.card_name && ` · ${entry.card_name}`}
                          {entry.installment_no !== null &&
                            entry.installment_count !== null &&
                            ` · ${entry.installment_no}/${entry.installment_count}`}
                          {entry.wallet !== "conta" && ` · ${entry.wallet.toUpperCase()}`}
                        </span>
                      </span>
                      <span
                        className="tabular shrink-0 text-[15px] font-semibold"
                        style={{ color: income ? "var(--success)" : "var(--text-primary)" }}
                      >
                        {income ? "+" : "−"}
                        {formatAmount(entry.amount_brl)}
                      </span>
                      <ChevronDown
                        size={15}
                        strokeWidth={1.8}
                        aria-hidden
                        className="shrink-0 transition-transform duration-200"
                        style={{
                          color: "var(--text-muted)",
                          transform: open ? "rotate(180deg)" : "none",
                        }}
                      />
                    </button>

                    <AnimatePresence initial={false}>
                      {open && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                          className="overflow-hidden"
                        >
                          <div
                            className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 text-[12px]"
                            style={{ color: "var(--text-muted)" }}
                          >
                            <span>Registrado pelo {sourceLabel(entry.source)}</span>
                            <span className="flex gap-2">
                              {group && (
                                <button
                                  type="button"
                                  onClick={() => void removeGroup(group)}
                                  className="flex min-h-[2.75rem] items-center gap-1.5 rounded-md border px-3 font-medium"
                                  style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                                >
                                  <Trash2 size={14} strokeWidth={1.9} />
                                  Excluir compra ({entry.installment_count} parcelas)
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => void remove(entry.id)}
                                className="flex min-h-[2.75rem] items-center gap-1.5 rounded-md border px-3 font-medium"
                                style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                              >
                                <Trash2 size={14} strokeWidth={1.9} />
                                {group ? "Excluir parcela" : "Excluir"}
                              </button>
                            </span>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
};

export default ExtratoPage;
