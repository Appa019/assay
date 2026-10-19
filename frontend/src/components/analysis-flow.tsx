"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  Loader2,
  Plus,
  RefreshCw,
} from "lucide-react";
import type { Contribution, Prompt } from "@/lib/api";
import { MarkdownViewer } from "@/components/markdown-viewer";
import {
  describeRunFailure,
  formatBRL,
  formatDateLong,
  formatScheduledFor,
  stripMachineBlocks,
} from "@/lib/format";

const POLL_INTERVAL_MS = 4000;
// A scheduled run only needs to notice that it started.
const SCHEDULED_POLL_MS = 60_000;

export const isRunFailed = (c: Contribution): boolean =>
  c.status === "ready" && (c.notes ?? "").startsWith("[run failed");

/** Waiting for its night slot: nothing ran yet and nothing is running. */
export const isRunScheduled = (c: Contribution): boolean =>
  Boolean(c.scheduled_for) &&
  c.status !== "completed" &&
  c.status !== "in_progress" &&
  !isRunFailed(c) &&
  c.prompts.every((p) => !p.response);

type StepState = "done" | "running" | "pending";
type RunState = "scheduled" | "running" | "failed" | "completed";

/**
 * Live view of a contribution analysis. Before the run: when it is scheduled.
 * During: the chained committee steps filling in. After: `children` (the order
 * sheet) first, then the closing summary, with the meeting minutes folded
 * away. Polls while the run is in flight; `resuming` keeps the polling alive
 * right after a retry, before the backend flips the status back to in_progress.
 */
export const AnalysisFlow = ({
  contribution,
  onPoll,
  onRetry,
  resuming = false,
  retryError = null,
  children,
}: {
  contribution: Contribution;
  onPoll: () => Promise<void>;
  onRetry: () => Promise<void>;
  resuming?: boolean;
  retryError?: string | null;
  children?: ReactNode;
}) => {
  const orderedPrompts = useMemo(
    () => [...contribution.prompts].sort((a, b) => a.prompt_order - b.prompt_order),
    [contribution.prompts]
  );

  const runState: RunState =
    contribution.status === "completed"
      ? "completed"
      : isRunFailed(contribution) && !resuming
        ? "failed"
        : isRunScheduled(contribution) && !resuming
          ? "scheduled"
          : "running";
  const isRunning = runState === "running";

  useEffect(() => {
    if (runState !== "running" && runState !== "scheduled") return;
    const timer = setInterval(
      () => {
        void onPoll();
      },
      runState === "running" ? POLL_INTERVAL_MS : SCHEDULED_POLL_MS
    );
    return () => clearInterval(timer);
  }, [runState, onPoll]);

  const answeredCount = orderedPrompts.filter((p) => p.response).length;
  const totalSteps = orderedPrompts.length + 1; // + fechamento
  const doneSteps = answeredCount + (runState === "completed" ? 1 : 0);

  // The first prompt without a response is the one currently running.
  const runningIndex = isRunning ? orderedPrompts.findIndex((p) => !p.response) : -1;

  const stepStateFor = (idx: number): StepState => {
    if (orderedPrompts[idx].response) return "done";
    if (isRunning && idx === runningIndex) return "running";
    return "pending";
  };

  const synthesisState: StepState =
    runState === "completed" ? "done" : isRunning && runningIndex === -1 ? "running" : "pending";

  const steps = (
    <div className="space-y-4">
      {orderedPrompts.map((prompt, idx) => (
        <StepCard key={prompt.id} prompt={prompt} state={stepStateFor(idx)} />
      ))}
      <SynthesisCard state={synthesisState} stepNumber={totalSteps} />
    </div>
  );

  return (
    <div className="max-w-5xl space-y-8 md:space-y-10">
      <header>
        <p
          className="text-[11px] uppercase tracking-[0.18em] font-medium mb-2 break-words"
          style={{ color: "var(--text-muted)" }}
        >
          Aporte · {formatDateLong(contribution.created_at)}
        </p>
        <h2
          className="text-3xl md:text-4xl tracking-tight leading-tight tabular"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          {formatBRL(contribution.amount_brl)}
        </h2>
        {/* Wraps below md: the bar takes its own line, meta + badge the next. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-3">
          {runState !== "scheduled" && (
            <>
              <ProgressBar value={doneSteps} total={totalSteps} />
              <span
                className="text-xs font-medium tabular"
                style={{ color: "var(--text-secondary)" }}
              >
                {doneSteps} de {totalSteps} etapas
              </span>
            </>
          )}
          <StatusBadge state={runState} scheduledFor={contribution.scheduled_for ?? null} />
        </div>
      </header>

      {runState === "scheduled" && contribution.scheduled_for && (
        <Notice tone="accent">
          <strong>Roda {formatScheduledFor(contribution.scheduled_for)}.</strong> De madrugada
          porque o comitê divide o limite de uso com o consultor. A folha de ordens fica pronta
          cerca de 90 minutos depois e chega um aviso no app.
        </Notice>
      )}

      {runState === "running" && (
        <Notice tone="accent">
          O comitê está reunido no servidor. Cada reunião leva de 10 a 30 minutos. Pode fechar
          esta aba: a página retoma de onde estiver.
        </Notice>
      )}

      {runState === "failed" && (
        <FailureNotice notes={contribution.notes} retryError={retryError} onRetry={onRetry} />
      )}

      {runState === "completed" ? (
        <>
          {children}
          {contribution.final_summary && <FinalSummary summary={contribution.final_summary} />}
          <details className="group">
            <summary
              className="flex items-center justify-between cursor-pointer min-h-11 px-4 py-3 rounded-md text-sm font-medium list-none"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                color: "var(--text-secondary)",
              }}
            >
              Atas das {orderedPrompts.length} reuniões
              <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
            </summary>
            <div className="mt-4">{steps}</div>
          </details>
        </>
      ) : (
        steps
      )}

      <div className="flex flex-col gap-3 md:flex-row">
        <Link
          href="/investimentos?aba=aportar"
          className="flex items-center justify-center gap-2 min-h-11 px-5 py-2.5 rounded-md text-sm font-semibold md:min-h-0"
          style={{ background: "var(--accent)", color: "white" }}
        >
          <Plus size={14} />
          Novo aporte
        </Link>
        <Link
          href="/investimentos?aba=analises"
          className="flex items-center justify-center min-h-11 px-5 py-2.5 rounded-md text-sm font-medium md:min-h-0"
          style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
        >
          Ver análises
        </Link>
      </div>
    </div>
  );
};

const Notice = ({ tone, children }: { tone: "accent"; children: ReactNode }) => (
  <section
    className="p-4 md:p-5 rounded-md text-sm leading-relaxed"
    style={{
      background: tone === "accent" ? "var(--accent-light)" : undefined,
      color: "var(--text-primary)",
    }}
  >
    {children}
  </section>
);

const FailureNotice = ({
  notes,
  retryError,
  onRetry,
}: {
  notes: string | null;
  retryError: string | null;
  onRetry: () => Promise<void>;
}) => {
  const { message, detail } = describeRunFailure(notes);
  return (
    <section
      className="p-4 md:p-5 rounded-md flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-4"
      style={{ background: "var(--danger-light)", border: "1px solid var(--danger)" }}
    >
      <div className="flex items-start gap-3 min-w-0">
        <AlertTriangle size={16} style={{ color: "var(--danger)" }} className="mt-0.5 shrink-0" />
        <div className="text-sm leading-relaxed min-w-0 break-words" style={{ color: "var(--text-primary)" }}>
          <strong>A análise parou.</strong> {message}
          {detail && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs" style={{ color: "var(--text-secondary)" }}>
                Detalhe técnico
              </summary>
              <p className="mt-1 text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                {detail}
              </p>
            </details>
          )}
          {retryError && (
            <p className="mt-1.5 font-medium" style={{ color: "var(--danger)" }}>
              {retryError}
            </p>
          )}
        </div>
      </div>
      <button
        onClick={() => void onRetry()}
        className="flex items-center justify-center gap-2 min-h-11 w-full px-4 py-2 rounded-md text-xs font-semibold shrink-0 md:min-h-0 md:w-auto"
        style={{ background: "var(--accent)", color: "white" }}
      >
        <RefreshCw size={13} />
        Retomar agora
      </button>
    </section>
  );
};

const StatusBadge = ({
  state,
  scheduledFor,
}: {
  state: RunState;
  scheduledFor: string | null;
}) => {
  const label =
    state === "failed"
      ? "Parou"
      : state === "completed"
        ? "Concluído"
        : state === "scheduled"
          ? scheduledFor
            ? `Agendado · ${formatScheduledFor(scheduledFor)}`
            : "Agendado"
          : "Rodando";
  const color =
    state === "failed"
      ? "var(--danger)"
      : state === "completed"
        ? "var(--success)"
        : "var(--accent-strong)";
  return (
    <span
      className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] px-2.5 py-1 rounded-full"
      style={{ color, background: "var(--bg-secondary)" }}
    >
      {state === "running" && <Loader2 size={11} className="animate-spin" />}
      {state === "scheduled" && <Clock size={11} />}
      {label}
    </span>
  );
};

const FinalSummary = ({ summary }: { summary: string }) => (
  <motion.section
    initial={{ opacity: 0, y: 12 }}
    animate={{ opacity: 1, y: 0 }}
    className="p-4 md:p-7 rounded-md"
    style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
  >
    <h3
      className="text-2xl tracking-tight mb-5"
      style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
    >
      Fechamento do comitê
    </h3>
    <MarkdownViewer content={stripMachineBlocks(summary)} />
  </motion.section>
);

const ProgressBar = ({ value, total }: { value: number; total: number }) => {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div
      // Full-width bar on its own line below md; capped 200px track at md+.
      className="w-full h-1 rounded-full overflow-hidden md:w-auto md:flex-1 md:max-w-[200px]"
      style={{ background: "var(--bg-secondary)" }}
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

const StepIcon = ({ state, fallback }: { state: StepState; fallback: string }) => (
  <div
    className="flex items-center justify-center w-8 h-8 rounded-md text-xs font-semibold shrink-0 tabular"
    style={{
      background: state === "running" ? "var(--accent-light)" : "var(--bg-secondary)",
      color:
        state === "done"
          ? "var(--success)"
          : state === "running"
            ? "var(--accent-strong)"
            : "var(--text-muted)",
    }}
  >
    {state === "done" ? (
      <Check size={14} />
    ) : state === "running" ? (
      <Loader2 size={14} className="animate-spin" />
    ) : (
      fallback
    )}
  </div>
);

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest > 0 ? `${minutes}min ${rest}s` : `${minutes}min`;
};

const formatUSD = (value: number): string =>
  `US$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const stepMeta = (prompt: Prompt): string | null => {
  const parts = [
    prompt.cost_usd !== null ? formatUSD(prompt.cost_usd) : null,
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
      animate={{ opacity: state === "pending" ? 0.55 : 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="rounded-md overflow-hidden"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${state === "running" ? "var(--accent)" : "var(--border)"}`,
      }}
    >
      {/* Below md the step is a compact vertical block: header row, then the
          toggle as a full-width control. */}
      <header className="px-4 py-4 md:px-7 md:py-5 flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-4">
        <div className="flex items-start gap-3 min-w-0 md:gap-4">
          <StepIcon state={state} fallback={stepLabel} />
          <div className="min-w-0">
            <h3
              className="text-lg md:text-xl tracking-tight leading-snug break-words"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              {prompt.title}
            </h3>
            <p
              className="text-xs mt-1.5 max-w-2xl leading-relaxed break-words"
              style={{ color: "var(--text-secondary)" }}
            >
              {state === "running" ? "Reunião em andamento…" : prompt.description}
            </p>
            {meta && (
              <p className="text-xs mt-1 tabular" style={{ color: "var(--text-muted)" }}>
                {meta}
              </p>
            )}
          </div>
        </div>
        {prompt.response ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center justify-center gap-1 min-h-11 w-full text-xs font-medium px-2.5 py-1.5 rounded-md shrink-0 md:min-h-0 md:w-auto"
            style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Recolher" : "Ler ata"}
          </button>
        ) : (
          state === "pending" && (
            <Circle
              size={20}
              style={{ color: "var(--border-strong)" }}
              className="hidden shrink-0 md:block"
            />
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
            <div className="px-4 pb-5 space-y-4 md:px-7 md:pb-7">
              <div
                className="rounded-md p-3 md:p-5 min-w-0"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                <MarkdownViewer content={prompt.response} maxHeight={560} />
              </div>
              <details>
                <summary
                  className="cursor-pointer text-[11px] uppercase tracking-[0.16em] font-medium min-h-11 py-3.5 md:min-h-0 md:py-0"
                  style={{ color: "var(--text-muted)" }}
                >
                  Ver prompt enviado
                </summary>
                <pre
                  className="mt-3 p-3 md:p-4 rounded-md text-[12px] leading-relaxed whitespace-pre-wrap break-words font-mono max-h-80 overflow-auto"
                  style={{
                    background: "var(--bg-secondary)",
                    color: "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {prompt.content}
                </pre>
              </details>
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
    animate={{ opacity: state === "pending" ? 0.55 : 1, y: 0 }}
    transition={{ duration: 0.25, ease: "easeOut" }}
    className="rounded-md"
    style={{
      background: "var(--bg-card)",
      border: `1px solid ${state === "running" ? "var(--accent)" : "var(--border)"}`,
    }}
  >
    <header className="px-4 py-4 gap-3 md:px-7 md:py-5 md:gap-4 flex items-center">
      <StepIcon state={state} fallback={String(stepNumber).padStart(2, "0")} />
      <div className="min-w-0">
        <h3
          className="text-lg md:text-xl tracking-tight leading-snug break-words"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Fechamento executivo
        </h3>
        <p
          className="text-xs mt-1.5 leading-relaxed break-words"
          style={{ color: "var(--text-secondary)" }}
        >
          {state === "running"
            ? "Consolidando onde investir e quanto…"
            : "Folha de ordens final consolidada do comitê"}
        </p>
      </div>
    </header>
  </motion.article>
);
