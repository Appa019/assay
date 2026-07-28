"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Sparkles,
  Trash2,
  WifiOff,
} from "lucide-react";
import { useCashflow } from "@/hooks/use-cashflow";
import {
  classifyCashflow,
  createCashflowEntry,
  currentMonth,
  deleteCashflowEntry,
  type CashflowEntry,
  type CashflowKind,
} from "@/lib/api";
import { formatBRL, parseLocalDate } from "@/lib/format";

const MONTH_NAMES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
] as const;

/** Fallback chips before the month has any history to learn from. */
const SEED_CATEGORIES: Record<CashflowKind, readonly string[]> = {
  expense: ["mercado", "transporte", "alimentação", "casa", "saúde", "lazer", "outros"],
  income: ["salário", "freelance", "dividendos", "reembolso", "outros"],
};

const shiftMonth = (month: string, delta: number): string => {
  const [year, m] = month.split("-").map(Number);
  const date = new Date(year, m - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
};

const monthLabel = (month: string): string => {
  const [year, m] = month.split("-").map(Number);
  return `${MONTH_NAMES[m - 1]} de ${year}`;
};

/** "12,50" and "12.50" both mean the same thing to a Brazilian thumb. */
const parseAmount = (raw: string): number | null => {
  const normalized = raw.trim().replace(/\./g, "").replace(",", ".");
  const value = Number(normalized);
  return Number.isFinite(value) && value > 0 ? value : null;
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

const FinancasPage = () => {
  const [month, setMonth] = useState(currentMonth());
  const { entries, summary, loading, error, refresh } = useCashflow(month);

  const [kind, setKind] = useState<CashflowKind>("expense");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("outros");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");
  const [reading, setReading] = useState(false);
  const [occurredOn, setOccurredOn] = useState<string | null>(null);

  const isCurrent = month === currentMonth();

  // Chips he actually uses, most-used first, topped up with the seeds.
  const categories = useMemo(() => {
    const used = (summary?.by_category ?? [])
      .filter((c) => c.kind === kind)
      .map((c) => c.category);
    return [...new Set([...used, ...SEED_CATEGORIES[kind]])].slice(0, 8);
  }, [summary, kind]);

  // Switching kind swaps the whole chip set, so a category carried over from
  // the other side would sit selected but invisible.
  const switchKind = (next: CashflowKind) => {
    setKind(next);
    setCategory("outros");
  };

  const byDay = useMemo(() => {
    const groups = new Map<string, CashflowEntry[]>();
    for (const entry of entries ?? []) {
      const list = groups.get(entry.occurred_on) ?? [];
      list.push(entry);
      groups.set(entry.occurred_on, list);
    }
    return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [entries]);

  const expenseBars = useMemo(() => {
    const rows = (summary?.by_category ?? []).filter((c) => c.kind === "expense");
    const top = rows[0]?.total_brl ?? 0;
    return rows.slice(0, 6).map((row) => ({
      ...row,
      share: top > 0 ? (row.total_brl / top) * 100 : 0,
    }));
  }, [summary]);

  const interpret = async () => {
    const text = phrase.trim();
    if (!text) return;
    setReading(true);
    setFormError(null);
    try {
      const draft = await classifyCashflow(text);
      setKind(draft.kind);
      setAmount(String(draft.amount_brl).replace(".", ","));
      setCategory(draft.category ?? "outros");
      setDescription(draft.description ?? "");
      setOccurredOn(draft.occurred_on ?? null);
      setPhrase("");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Não entendi a frase.");
    } finally {
      setReading(false);
    }
  };

  const submit = async () => {
    const value = parseAmount(amount);
    if (value === null) {
      setFormError("Informe um valor maior que zero.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await createCashflowEntry({
        kind,
        amount_brl: value,
        category: category.trim().toLowerCase() || "outros",
        description: description.trim() || null,
        occurred_on: occurredOn ?? undefined,
      });
      setAmount("");
      setDescription("");
      setOccurredOn(null);
      await refresh();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Não foi possível salvar.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    setOpenId(null);
    try {
      await deleteCashflowEntry(id);
      await refresh();
    } catch {
      setFormError("Não foi possível excluir o lançamento.");
    }
  };

  const net = summary?.net_brl ?? 0;
  const netColor =
    net > 0 ? "var(--success)" : net < 0 ? "var(--danger)" : "var(--text-secondary)";

  return (
    <div className="pb-4">
      <header className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p
            className="text-[11px] uppercase tracking-[0.18em]"
            style={{ color: "var(--text-muted)" }}
          >
            Finanças pessoais
          </p>
          <h2
            className="text-[1.7rem] md:text-3xl leading-tight truncate first-letter:uppercase"
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

      {/* Net of the month, the one number worth reading from across the room. */}
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
          {loading && !summary ? "—" : formatBRL(net)}
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
      </section>

      {/* The most frequent action in the whole product: log something. Inline,
          always visible, never behind a modal. */}
      <section
        className="mt-7 rounded-xl border p-4"
        style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
      >
        {/* The fast path: say it, the model fills the form, you confirm. The
            structured fields below stay the source of truth so a misread never
            reaches the ledger unseen. */}
        <div className="flex items-center gap-2">
          <input
            value={phrase}
            onChange={(e) => setPhrase(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void interpret();
            }}
            placeholder="gastei 42,90 no mercado ontem"
            aria-label="Descreva o lançamento"
            enterKeyHint="go"
            className="w-full min-w-0 rounded-md border bg-transparent px-3.5 py-2.5 text-base outline-none"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          />
          <button
            type="button"
            onClick={() => void interpret()}
            disabled={reading || phrase.trim().length === 0}
            aria-label="Interpretar frase"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--accent)", color: "var(--accent-strong)" }}
          >
            {reading ? (
              <Loader2 size={17} className="animate-spin" />
            ) : (
              <Sparkles size={17} strokeWidth={1.9} />
            )}
          </button>
        </div>

        <div
          className="my-3.5 flex items-center gap-3 text-[10px] uppercase tracking-[0.16em]"
          style={{ color: "var(--text-muted)" }}
        >
          <span className="h-px flex-1" style={{ background: "var(--border)" }} />
          ou preencha
          <span className="h-px flex-1" style={{ background: "var(--border)" }} />
        </div>

        <div
          className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border"
          style={{ borderColor: "var(--border)", background: "var(--border)" }}
          role="group"
          aria-label="Tipo do lançamento"
        >
          {(
            [
              { value: "expense", label: "Gasto", tint: "var(--danger)" },
              { value: "income", label: "Ganho", tint: "var(--success)" },
            ] as const
          ).map(({ value, label, tint }) => {
            const active = kind === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => switchKind(value)}
                aria-pressed={active}
                className="min-h-[2.75rem] text-sm font-semibold transition-colors"
                style={{
                  background: active
                    ? `color-mix(in oklch, ${tint} 12%, var(--bg-card))`
                    : "var(--bg-card)",
                  color: active ? tint : "var(--text-muted)",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex items-center gap-2">
          <span
            className="text-lg font-medium shrink-0"
            style={{ color: "var(--text-muted)" }}
          >
            R$
          </span>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
            inputMode="decimal"
            enterKeyHint="done"
            placeholder="0,00"
            aria-label="Valor"
            className="tabular w-full min-w-0 rounded-md border bg-transparent px-3 py-2.5 text-[1.35rem] font-semibold outline-none"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          />
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {categories.map((name) => {
            const active = category === name;
            return (
              <button
                key={name}
                type="button"
                onClick={() => setCategory(name)}
                aria-pressed={active}
                className="min-h-[2.75rem] rounded-full border px-4 text-[13px] font-medium capitalize transition-colors"
                style={{
                  borderColor: active ? "var(--accent)" : "var(--border)",
                  background: active ? "var(--accent-light)" : "transparent",
                  color: active ? "var(--accent-strong)" : "var(--text-secondary)",
                }}
              >
                {name}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex gap-2">
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
            placeholder="Descrição (opcional)"
            aria-label="Descrição"
            enterKeyHint="done"
            className="w-full min-w-0 rounded-md border bg-transparent px-3 py-2.5 text-base outline-none"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={saving}
            className="grid min-h-[2.75rem] shrink-0 place-items-center rounded-md px-5 text-sm font-semibold disabled:opacity-60"
            style={{ background: "var(--accent)", color: "white" }}
          >
            {saving ? <Loader2 size={17} className="animate-spin" /> : "Salvar"}
          </button>
        </div>

        {formError && (
          <p className="mt-2.5 text-[13px]" style={{ color: "var(--danger)" }}>
            {formError}
          </p>
        )}
      </section>

      {expenseBars.length > 0 && (
        <section className="mt-9">
          <h2
            className="text-[11px] uppercase tracking-[0.18em]"
            style={{ color: "var(--text-muted)" }}
          >
            Para onde foi
          </h2>
          <div className="mt-3.5 flex flex-col gap-3">
            {expenseBars.map((row) => (
              <div key={row.category}>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="capitalize truncate" style={{ color: "var(--text-primary)" }}>
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
                    style={{ width: `${row.share}%`, background: "var(--accent)" }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mt-9">
        <h2
          className="text-[11px] uppercase tracking-[0.18em]"
          style={{ color: "var(--text-muted)" }}
        >
          Lançamentos
        </h2>

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
          <p className="mt-3.5 text-sm" style={{ color: "var(--text-secondary)" }}>
            Nenhum lançamento em {monthLabel(month)}. Registre acima, ou mande no
            Telegram e o consultor lança por você.
          </p>
        )}

        {byDay.map(([day, dayEntries]) => (
          <div key={day} className="mt-5">
            <p
              className="text-[11px] font-medium uppercase tracking-[0.14em]"
              style={{ color: "var(--text-muted)" }}
            >
              {dayLabel(day)}
            </p>

            <ul className="mt-2 overflow-hidden rounded-lg border" style={{ borderColor: "var(--border)" }}>
              {dayEntries.map((entry, index) => {
                const income = entry.kind === "income";
                const open = openId === entry.id;
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
                        </span>
                      </span>
                      <span
                        className="tabular shrink-0 text-[15px] font-semibold"
                        style={{ color: income ? "var(--success)" : "var(--text-primary)" }}
                      >
                        {income ? "+" : "−"}
                        {formatBRL(entry.amount_brl).replace("R$", "").trim()}
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
                            className="flex items-center justify-between gap-3 px-4 pb-3 text-[12px]"
                            style={{ color: "var(--text-muted)" }}
                          >
                            <span>
                              Registrado via {entry.source === "api" ? "site" : entry.source}
                            </span>
                            <button
                              type="button"
                              onClick={() => void remove(entry.id)}
                              className="flex min-h-[2.25rem] items-center gap-1.5 rounded-md border px-3 font-medium"
                              style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                            >
                              <Trash2 size={14} strokeWidth={1.9} />
                              Excluir
                            </button>
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

export default FinancasPage;
