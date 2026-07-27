"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Wallet,
} from "lucide-react";
import type { Contribution, Prompt } from "@/lib/api";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { formatDateLong, stripMachineBlocks } from "@/lib/format";

const POLL_INTERVAL_MS = 4000;

export const isRunFailed = (c: Contribution): boolean =>
  c.status === "ready" && (c.notes ?? "").startsWith("[run failed");

type StepState = "done" | "running" | "pending";

/**
 * Live view of a contribution analysis: chained committee steps, expandable
 * markdown responses and the final order sheet. Polls while the run is in
 * flight; `resuming` keeps the polling alive right after a retry, before the
 * backend flips the status back to in_progress.
 */
export const AnalysisFlow = ({
  contribution,
  onPoll,
  onRetry,
  resuming = false,
  retryError = null,
}: {
  contribution: Contribution;
  onPoll: () => Promise<void>;
  onRetry: () => Promise<void>;
  resuming?: boolean;
  retryError?: string | null;
}) => {
  const orderedPrompts = useMemo(
    () => [...contribution.prompts].sort((a, b) => a.prompt_order - b.prompt_order),
    [contribution.prompts]
  );

  const isCompleted = contribution.status === "completed";
  const failed = isRunFailed(contribution) && !resuming;
  const isRunning = !isCompleted && !failed;

  // Poll the backend while the run is in flight; each prompt response and the
  // final summary fill in as the chained Claude session advances.
  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => {
      void onPoll();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isRunning, onPoll]);

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
    <div className="max-w-5xl space-y-10">
      <header>
        <p
          className="text-[11px] uppercase tracking-[0.18em] font-medium mb-2"
          style={{ color: "var(--text-muted)" }}
        >
          Aporte #{contribution.id.slice(0, 8)} · {formatDateLong(contribution.created_at)}
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
            O comitê roda de forma autônoma no servidor (Opus · max · sessão única
            encadeada). Cada reunião pode levar minutos — pode fechar esta aba: a
            análise continua e esta página retoma de onde estiver ao reabrir.
          </div>
        </section>
      )}

      {failed && (
        <section
          className="p-5 rounded-md flex items-start justify-between gap-4"
          style={{ background: "var(--danger-light)", border: "1px solid var(--danger)" }}
        >
          <div className="flex items-start gap-3">
            <AlertTriangle size={16} style={{ color: "var(--danger)" }} className="mt-0.5 shrink-0" />
            <div className="text-xs leading-relaxed" style={{ color: "var(--text-primary)" }}>
              <strong>A análise falhou.</strong>{" "}
              <span style={{ color: "var(--text-secondary)" }}>{contribution.notes}</span>
              {retryError && (
                <p className="mt-1.5 font-medium" style={{ color: "var(--danger)" }}>
                  {retryError}
                </p>
              )}
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
        <Link
          href="/aporte"
          className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold"
          style={{ background: "var(--accent)", color: "white" }}
        >
          <Plus size={14} />
          Novo aporte
        </Link>
        <Link
          href="/relatorios"
          className="px-5 py-2.5 rounded-md text-sm font-medium"
          style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
        >
          Ver histórico
        </Link>
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
    <div className="flex items-center gap-2.5 mb-5">
      <Wallet size={18} style={{ color: "var(--success)" }} />
      <h3
        className="text-2xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Onde investir e quanto
      </h3>
    </div>
    <MarkdownViewer content={stripMachineBlocks(summary)} />
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

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest > 0 ? `${minutes}min ${rest}s` : `${minutes}min`;
};

const stepMeta = (prompt: Prompt): string | null => {
  const parts = [
    prompt.cost_usd !== null ? `US$ ${prompt.cost_usd.toFixed(2)}` : null,
    prompt.duration_s !== null ? formatDuration(prompt.duration_s) : null,
    prompt.num_turns !== null ? `${prompt.num_turns} turnos` : null,
  ].filter((p): p is string => p !== null);
  return parts.length > 0 ? parts.join(" · ") : null;
};

const StepCard = ({ prompt, state }: { prompt: Prompt; state: StepState }) => {
  const [expanded, setExpanded] = useState(false);
  const stepLabel = String(prompt.prompt_order).padStart(2, "0");
  const meta = prompt.response ? stepMeta(prompt) : null;

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
              {state === "running" ? "Reunião em andamento…" : prompt.description}
            </p>
            {meta && (
              <p className="text-[11px] mt-1 tabular" style={{ color: "var(--text-muted)" }}>
                {meta}
              </p>
            )}
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
        ) : (
          state === "pending" && (
            <Circle size={20} style={{ color: "var(--border-strong)" }} className="shrink-0" />
          )
        )}
      </header>

      <AnimatePresence initial={false}>
        {expanded && prompt.response && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-7 pb-7 space-y-4">
              <details>
                <summary
                  className="cursor-pointer text-[11px] uppercase tracking-[0.16em] font-medium"
                  style={{ color: "var(--text-muted)" }}
                >
                  Ver prompt enviado
                </summary>
                <pre
                  className="mt-3 p-4 rounded-md text-[12px] leading-relaxed whitespace-pre-wrap font-mono max-h-80 overflow-auto"
                  style={{
                    background: "var(--bg-secondary)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {prompt.content}
                </pre>
              </details>
              <div
                className="rounded-md p-5"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                <MarkdownViewer content={prompt.response} maxHeight={560} />
              </div>
            </div>
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
