"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, RefreshCw, Send } from "lucide-react";
import { createContribution } from "@/lib/api";
import { useMacro } from "@/hooks/use-macro";

/**
 * New-contribution section. Exported by name so /investimentos can host it as
 * a sub-tab; the default export keeps this route alive for existing deep links.
 */
export const AporteView = () => {
  const router = useRouter();
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: macro, loading: macroLoading, refresh: refreshMacro } = useMacro();

  const handleAmountChange = (raw: string) => {
    const digits = raw.replace(/\D/g, "");
    if (!digits) {
      setAmount("");
      return;
    }
    const cents = parseInt(digits, 10);
    const formatted = (cents / 100).toLocaleString("pt-BR", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    setAmount(formatted);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const value = parseFloat(amount.replace(/\./g, "").replace(",", "."));
    if (Number.isNaN(value) || value <= 0) {
      setError("Informe um valor válido");
      return;
    }
    setSubmitting(true);
    try {
      // Create + trigger the headless analysis, then hand off to the
      // dedicated page — closing the tab there loses nothing.
      const created = await createContribution(value, notes || undefined, true);
      router.push(`/aporte/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao iniciar análise");
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl space-y-9 md:space-y-12">
      <header>
        <h2
          className="text-4xl md:text-5xl tracking-tight leading-[1.05]"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Novo aporte
        </h2>
        <p
          className="mt-3 text-sm leading-relaxed max-w-xl"
          style={{ color: "var(--text-secondary)" }}
        >
          Informe o valor. O sistema captura o macro (BCB · Yahoo · CoinGecko),
          fotografa sua carteira e roda as 5 reuniões do comitê + fechamento no
          Claude Code sozinho — cada reunião encadeada na anterior. Você
          acompanha etapa por etapa e recebe, no fim, onde investir e quanto.
        </p>
      </header>

      <section
        className="p-5 md:p-9 rounded-md"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <form onSubmit={handleSubmit} className="space-y-6 md:space-y-7">
          <div>
            <label
              htmlFor="amount"
              className="block text-[11px] font-medium uppercase tracking-[0.18em] mb-3"
              style={{ color: "var(--text-muted)" }}
            >
              Valor do aporte
            </label>
            <div className="relative">
              <span
                className="absolute left-4 top-1/2 -translate-y-1/2 text-sm font-medium tabular"
                style={{ color: "var(--text-muted)" }}
              >
                R$
              </span>
              <input
                id="amount"
                // `decimal` opens the numeric keypad with a separator on iOS;
                // non-digits are stripped by the mask anyway.
                inputMode="decimal"
                autoFocus
                value={amount}
                onChange={(e) => handleAmountChange(e.target.value)}
                placeholder="0,00"
                className="w-full min-h-14 pl-12 pr-4 py-3.5 rounded-md text-2xl font-semibold tabular outline-none transition-colors"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                  fontFamily: "var(--font-body)",
                  // The unlayered `input { font-size }` floor in globals.css
                  // outranks any utility class, so the hero field states its
                  // size inline to keep the 24px hierarchy on phones too —
                  // still well clear of the 16px iOS zoom threshold.
                  fontSize: "1.5rem",
                }}
              />
            </div>
          </div>

          <div>
            <label
              htmlFor="notes"
              className="block text-[11px] font-medium uppercase tracking-[0.18em] mb-3"
              style={{ color: "var(--text-muted)" }}
            >
              Notas (opcional)
            </label>
            <input
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="ex: aporte de bonus, foco em RF curto"
              // 16px on phones keeps iOS from zooming the viewport on focus.
              className="w-full min-h-12 md:min-h-0 px-4 py-3 rounded-md text-base md:text-sm outline-none transition-colors"
              style={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          <AnimatePresence>
            {error && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="text-sm font-medium"
                style={{ color: "var(--danger)" }}
              >
                {error}
              </motion.p>
            )}
          </AnimatePresence>

          {/* Full-width submit on phones: bottom of the card, inside thumb reach. */}
          <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={submitting || !amount}
              className="flex items-center justify-center md:justify-start gap-2.5 w-full md:w-auto min-h-12 md:min-h-0 px-6 py-3 rounded-md text-sm font-semibold transition-opacity disabled:opacity-40"
              style={{ background: "var(--accent)", color: "white" }}
            >
              <Send size={15} />
              {submitting ? "Iniciando..." : "Adicionar aporte e rodar análise"}
            </button>
          </div>
        </form>
      </section>

      <MacroPreview loading={macroLoading} macro={macro} onRefresh={refreshMacro} />
    </div>
  );
};

const MacroPreview = ({
  loading,
  macro,
  onRefresh,
}: {
  loading: boolean;
  macro: ReturnType<typeof useMacro>["data"];
  onRefresh: () => void;
}) => {
  return (
    <section className="space-y-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h3
            className="text-xl tracking-tight"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Dados que serão injetados na análise
          </h3>
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            Capturados ao vivo · qualquer dado faltante será sinalizado aos comitês
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center justify-center gap-1.5 self-start md:self-auto text-xs font-medium min-h-11 px-4 md:min-h-0 md:px-3 md:py-1.5 rounded-md transition-colors"
          style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          Atualizar
        </button>
      </div>

      {macro ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <MacroCard label="Selic" value={macro.macro.selic} unit="% a.a." />
          <MacroCard label="IPCA 12m" value={macro.macro.ipca_12m} unit="%" />
          <MacroCard label="CDI" value={macro.macro.cdi} unit="% a.a." />
          <MacroCard label="USD/BRL" value={macro.macro.usd_brl} prefix="R$ " />
          <MacroCard label="Ibovespa" value={macro.ibovespa.level} unit=" pts" />
          <MacroCard label="Ibov 30d" value={macro.ibovespa.month_return_pct} unit="%" signed />
          <MacroCard label="BTC Dom" value={macro.crypto_global.btc_dominance} unit="%" />
          <MacroCard label="Fear & Greed" value={macro.fear_greed_index} />
        </div>
      ) : (
        <div
          className="p-6 text-sm rounded-md"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
            color: "var(--text-muted)",
          }}
        >
          {loading ? "Capturando macro..." : "Sem dados ainda"}
        </div>
      )}

      {macro?.warnings?.length ? (
        <div
          className="p-3.5 rounded-md flex items-start gap-2.5"
          style={{ background: "var(--warning-light)", border: "1px solid var(--warning)" }}
        >
          <AlertTriangle size={14} style={{ color: "var(--warning)" }} className="mt-0.5 shrink-0" />
          <div className="text-xs leading-relaxed">
            <strong>Avisos do pipeline:</strong>{" "}
            <span style={{ color: "var(--text-secondary)" }}>{macro.warnings.join(" · ")}</span>
          </div>
        </div>
      ) : null}
    </section>
  );
};

const MacroCard = ({
  label,
  value,
  unit,
  prefix,
  signed,
}: {
  label: string;
  value: number | null;
  unit?: string;
  prefix?: string;
  signed?: boolean;
}) => {
  const formatted =
    value === null || value === undefined
      ? "—"
      : `${prefix ?? ""}${signed && value > 0 ? "+" : ""}${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}${unit ?? ""}`;

  return (
    <div
      className="p-3.5 md:p-4 rounded-md"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <p
        className="text-[10px] uppercase tracking-[0.16em] font-medium"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </p>
      <p
        className="text-base md:text-lg font-semibold tabular mt-1.5"
        style={{ color: value === null ? "var(--text-muted)" : "var(--text-primary)" }}
      >
        {formatted}
      </p>
    </div>
  );
};

export default AporteView;
