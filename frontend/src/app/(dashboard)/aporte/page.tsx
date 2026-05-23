"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Check,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Circle,
  Loader2,
  RefreshCw,
  Sparkles,
  AlertTriangle,
  Wallet,
} from "lucide-react";
import {
  createContribution,
  fetchContribution,
  runContribution,
  type Contribution,
  type Prompt,
} from "@/lib/api";
import { useMacro } from "@/hooks/use-macro";

const POLL_INTERVAL_MS = 4000;

const isRunFailed = (c: Contribution): boolean =>
  c.status === "ready" && (c.notes ?? "").startsWith("[run failed");

const AportePage = () => {
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contribution, setContribution] = useState<Contribution | null>(null);

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
      // Create + trigger the headless analysis in one shot.
      const created = await createContribution(value, notes || undefined, true);
      setContribution(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao iniciar análise");
    } finally {
      setSubmitting(false);
    }
  };

  const reload = useCallback(async (id: string) => {
    try {
      const fresh = await fetchContribution(id);
      setContribution(fresh);
      return fresh;
    } catch {
      return null;
    }
  }, []);

  const handleReset = () => {
    setContribution(null);
    setAmount("");
    setNotes("");
    setError(null);
    void refreshMacro();
  };

  const handleRetry = useCallback(async () => {
    if (!contribution) return;
    const updated = await runContribution(contribution.id);
    setContribution(updated);
  }, [contribution]);

  if (contribution) {
    return (
      <AnalysisFlow
        contribution={contribution}
        onPoll={reload}
        onReset={handleReset}
        onRetry={handleRetry}
      />
    );
  }

  return (
    <div className="max-w-3xl space-y-12">
      <header>
        <h2
          className="text-5xl tracking-tight leading-[1.05]"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Novo aporte
        </h2>
        <p
          className="mt-3 text-sm leading-relaxed max-w-xl"
          style={{ color: "var(--text-secondary)" }}
        >
          Informe o valor. O sistema captura o macro (BCB · Yahoo · CoinGecko),
          fotografa sua carteira e roda o comitê inteiro no Claude Code sozinho —
          cada reunião encadeada na anterior. Você acompanha etapa por etapa e
          recebe, no fim, onde investir e quanto.
        </p>
      </header>

      <section
        className="p-9 rounded-md"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <form onSubmit={handleSubmit} className="space-y-7">
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
                inputMode="numeric"
                autoFocus
                value={amount}
                onChange={(e) => handleAmountChange(e.target.value)}
                placeholder="0,00"
                className="w-full pl-12 pr-4 py-3.5 rounded-md text-2xl font-semibold tabular outline-none transition-colors"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                  fontFamily: "var(--font-body)",
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
              className="w-full px-4 py-3 rounded-md text-sm outline-none transition-colors"
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

          <div className="flex items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={submitting || !amount}
              className="flex items-center gap-2.5 px-6 py-3 rounded-md text-sm font-semibold transition-opacity disabled:opacity-40"
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
      <div className="flex items-center justify-between">
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
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md transition-colors"
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
      : `${prefix ?? ""}${signed && value > 0 ? "+" : ""}${typeof value === "number" ? value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : value}${unit ?? ""}`;

  return (
    <div
      className="p-4 rounded-md"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <p
        className="text-[10px] uppercase tracking-[0.16em] font-medium"
        style={{ color: "var(--text-muted)" }}
      >
        {label}
      </p>
      <p
        className="text-lg font-semibold tabular mt-1.5"
        style={{ color: value === null ? "var(--text-muted)" : "var(--text-primary)" }}
      >
        {formatted}
      </p>
    </div>
  );
};

type StepState = "done" | "running" | "pending";

const AnalysisFlow = ({
  contribution,
  onPoll,
  onReset,
  onRetry,
}: {
  contribution: Contribution;
  onPoll: (id: string) => Promise<Contribution | null>;
  onReset: () => void;
  onRetry: () => Promise<void>;
}) => {
  const orderedPrompts = useMemo(
    () => [...contribution.prompts].sort((a, b) => a.prompt_order - b.prompt_order),
    [contribution.prompts]
  );

  const isCompleted = contribution.status === "completed";
  const failed = isRunFailed(contribution);
  const isRunning = !isCompleted && !failed;

  // Poll the backend while the run is in flight; each prompt response and the
  // final summary fill in as the chained Claude session advances.
  useEffect(() => {
    if (!isRunning) return;
    const id = contribution.id;
    const timer = setInterval(() => {
      void onPoll(id);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isRunning, contribution.id, onPoll]);

  const answeredCount = orderedPrompts.filter((p) => p.response).length;
  const totalSteps = orderedPrompts.length + 1; // + fechamento
  const doneSteps = answeredCount + (isCompleted ? 1 : 0);

  // The first prompt without a response is the one currently running.
  const runningIndex = isRunning ? orderedPrompts.findIndex((p) => !p.response) : -1;

  const stepStateFor = (idx: number): StepState => {
    if (orderedPrompts[idx].response) return "done";
    if (isRunning && idx === runningIndex) return "running";
    return "pending";
  };

  const synthesisState: StepState = isCompleted
    ? "done"
    : isRunning && runningIndex === -1
      ? "running"
      : "pending";

  return (
    <div className="max-w-4xl space-y-10">
      <header>
        <p
          className="text-[11px] uppercase tracking-[0.18em] font-medium mb-2"
          style={{ color: "var(--text-muted)" }}
        >
          Aporte #{contribution.id.slice(0, 8)} ·{" "}
          {new Date(contribution.created_at).toLocaleDateString("pt-BR", {
            day: "2-digit",
            month: "long",
            year: "numeric",
          })}
        </p>
        <h2
          className="text-4xl tracking-tight leading-tight"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          R${" "}
          {contribution.amount_brl.toLocaleString("pt-BR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}
        </h2>
        <div className="flex items-center gap-4 mt-3">
          <ProgressBar value={doneSteps} total={totalSteps} />
          <span className="text-xs font-medium tabular" style={{ color: "var(--text-secondary)" }}>
            {doneSteps} de {totalSteps} etapas
          </span>
          <StatusBadge running={isRunning} completed={isCompleted} failed={failed} />
        </div>
      </header>

      {isRunning && (
        <section
          className="p-5 rounded-md flex items-start gap-3"
          style={{ background: "var(--accent-light)", border: "1px solid var(--accent)" }}
        >
          <Sparkles size={16} style={{ color: "var(--accent-strong)" }} className="mt-0.5 shrink-0" />
          <div className="text-xs leading-relaxed" style={{ color: "var(--text-primary)" }}>
            O Claude está rodando o comitê de forma autônoma (Opus · max · sessão
            única encadeada). Cada reunião pode levar minutos — pode fechar a aba,
            o resultado fica salvo no histórico.
          </div>
        </section>
      )}

      {failed && (
        <section
          className="p-5 rounded-md flex items-start justify-between gap-4"
          style={{ background: "var(--danger-light, #fdecec)", border: "1px solid var(--danger)" }}
        >
          <div className="flex items-start gap-3">
            <AlertTriangle size={16} style={{ color: "var(--danger)" }} className="mt-0.5 shrink-0" />
            <div className="text-xs leading-relaxed" style={{ color: "var(--text-primary)" }}>
              <strong>A análise falhou.</strong>{" "}
              <span style={{ color: "var(--text-secondary)" }}>{contribution.notes}</span>
            </div>
          </div>
          <button
            onClick={() => void onRetry()}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold shrink-0"
            style={{ background: "var(--accent)", color: "white" }}
          >
            <RefreshCw size={13} />
            Tentar novamente
          </button>
        </section>
      )}

      {isCompleted && contribution.final_summary && (
        <FinalSummary summary={contribution.final_summary} />
      )}

      <div className="space-y-4">
        {orderedPrompts.map((prompt, idx) => (
          <StepCard key={prompt.id} prompt={prompt} state={stepStateFor(idx)} />
        ))}
        <SynthesisCard state={synthesisState} stepNumber={totalSteps} />
      </div>

      <div className="flex gap-3">
        <button
          onClick={onReset}
          className="px-5 py-2.5 rounded-md text-sm font-semibold"
          style={{ background: "var(--accent)", color: "white" }}
        >
          Novo aporte
        </button>
      </div>
    </div>
  );
};

const StatusBadge = ({
  running,
  completed,
  failed,
}: {
  running: boolean;
  completed: boolean;
  failed: boolean;
}) => {
  const label = failed ? "Falhou" : completed ? "Concluído" : running ? "Rodando" : "Pronto";
  const color = failed ? "var(--danger)" : completed ? "var(--success)" : "var(--accent-strong)";
  return (
    <span
      className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] px-2.5 py-1 rounded-full"
      style={{ color, background: "var(--bg-secondary)" }}
    >
      {running && <Loader2 size={11} className="animate-spin" />}
      {label}
    </span>
  );
};

const FinalSummary = ({ summary }: { summary: string }) => (
  <motion.section
    initial={{ opacity: 0, y: 12 }}
    animate={{ opacity: 1, y: 0 }}
    className="p-7 rounded-md"
    style={{ background: "var(--success-light)", border: "1px solid var(--success)" }}
  >
    <div className="flex items-center gap-2.5 mb-4">
      <Wallet size={18} style={{ color: "var(--success)" }} />
      <h3
        className="text-2xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Onde investir e quanto
      </h3>
    </div>
    <pre
      className="text-[13px] leading-relaxed whitespace-pre-wrap"
      style={{ color: "var(--text-primary)", fontFamily: "var(--font-body)" }}
    >
      {summary}
    </pre>
  </motion.section>
);

const ProgressBar = ({ value, total }: { value: number; total: number }) => {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div
      className="flex-1 h-1 rounded-full overflow-hidden"
      style={{ background: "var(--bg-secondary)", maxWidth: 200 }}
    >
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="h-full"
        style={{ background: "var(--accent)" }}
      />
    </div>
  );
};

const StepIcon = ({ state, fallback }: { state: StepState; fallback: string }) => {
  if (state === "done")
    return (
      <div
        className="flex items-center justify-center w-10 h-10 rounded-md shrink-0"
        style={{ background: "var(--success)", color: "white" }}
      >
        <Check size={16} />
      </div>
    );
  if (state === "running")
    return (
      <div
        className="flex items-center justify-center w-10 h-10 rounded-md shrink-0"
        style={{ background: "var(--accent-light)", color: "var(--accent-strong)" }}
      >
        <Loader2 size={16} className="animate-spin" />
      </div>
    );
  return (
    <div
      className="flex items-center justify-center w-10 h-10 rounded-md text-sm font-semibold shrink-0"
      style={{
        background: "var(--bg-secondary)",
        color: "var(--text-muted)",
        fontFamily: "var(--font-heading)",
      }}
    >
      {fallback}
    </div>
  );
};

const StepCard = ({ prompt, state }: { prompt: Prompt; state: StepState }) => {
  const [expanded, setExpanded] = useState(false);
  const stepLabel = String(prompt.prompt_order).padStart(2, "0");

  return (
    <motion.article
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: state === "pending" ? 0.5 : 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-md overflow-hidden"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${state === "done" ? "var(--success)" : "var(--border)"}`,
      }}
    >
      <header className="px-7 py-5 flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <StepIcon state={state} fallback={stepLabel} />
          <div className="min-w-0">
            <h3
              className="text-xl tracking-tight leading-snug"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              {prompt.title}
            </h3>
            <p
              className="text-xs mt-1.5 max-w-2xl leading-relaxed"
              style={{ color: "var(--text-secondary)" }}
            >
              {state === "running" ? "Rodando no Claude…" : prompt.description}
            </p>
          </div>
        </div>
        {prompt.response ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-md shrink-0"
            style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Recolher" : "Ver resposta"}
          </button>
        ) : state === "pending" ? (
          <Circle size={20} style={{ color: "var(--border-strong)" }} className="shrink-0" />
        ) : (
          <CheckCircle2 size={20} style={{ color: "var(--accent-strong)" }} className="shrink-0 opacity-0" />
        )}
      </header>

      <AnimatePresence>
        {expanded && prompt.response && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="px-7 pb-7"
          >
            <pre
              className="rounded-md p-4 text-[12px] leading-relaxed overflow-auto whitespace-pre-wrap"
              style={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                color: "var(--text-secondary)",
                fontFamily: "var(--font-body)",
                maxHeight: 480,
              }}
            >
              {prompt.response}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
};

const SynthesisCard = ({ state, stepNumber }: { state: StepState; stepNumber: number }) => (
  <motion.article
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: state === "pending" ? 0.5 : 1, y: 0 }}
    transition={{ duration: 0.3 }}
    className="rounded-md"
    style={{
      background: "var(--bg-card)",
      border: `1px solid ${state === "done" ? "var(--success)" : "var(--border)"}`,
    }}
  >
    <header className="px-7 py-5 flex items-center gap-4">
      <StepIcon state={state} fallback={String(stepNumber).padStart(2, "0")} />
      <div>
        <h3
          className="text-xl tracking-tight leading-snug"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Fechamento executivo
        </h3>
        <p className="text-xs mt-1.5 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          {state === "running"
            ? "Consolidando onde investir e quanto…"
            : "Folha de ordens final consolidada do comitê"}
        </p>
      </div>
    </header>
  </motion.article>
);

export default AportePage;
