"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, FileQuestion, Loader2 } from "lucide-react";
import {
  ApiError,
  fetchContribution,
  runContribution,
  type Contribution,
} from "@/lib/api";
import { AnalysisFlow } from "@/components/analysis-flow";

const AporteDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const [contribution, setContribution] = useState<Contribution | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const fresh = await fetchContribution(id);
      setContribution(fresh);
      setLoadError(null);
      // Once the backend confirms the retried run is live (or done), the
      // failure banner can come back if it ever fails again.
      if (fresh.status === "in_progress" || fresh.status === "completed") {
        setResuming(false);
        setRetryError(null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        return;
      }
      // Network blip: keep the last snapshot on screen, polling will retry.
      setLoadError(err instanceof Error ? err.message : "Erro ao carregar aporte");
    }
  }, [id]);

  useEffect(() => {
    // Defer to a task so no state update runs synchronously in the effect.
    const timer = setTimeout(() => {
      void reload();
    }, 0);
    return () => clearTimeout(timer);
  }, [reload]);

  const handleRetry = useCallback(async () => {
    setRetryError(null);
    try {
      await runContribution(id);
      setResuming(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Analysis already running (e.g. resumed by the cron) — just watch it.
        setResuming(true);
      } else {
        setRetryError(err instanceof Error ? err.message : "Erro ao retomar análise");
        return;
      }
    }
    await reload();
  }, [id, reload]);

  if (notFound) {
    return (
      <div
        className="max-w-2xl text-center py-24 rounded-md"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <FileQuestion size={36} className="mx-auto mb-4" style={{ color: "var(--border-strong)" }} />
        <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
          Aporte não encontrado
        </p>
        <Link
          href="/relatorios"
          className="inline-flex items-center gap-2 mt-5 px-5 py-2.5 rounded-md text-sm font-semibold"
          style={{ background: "var(--accent)", color: "white" }}
        >
          <ArrowLeft size={13} />
          Voltar ao histórico
        </Link>
      </div>
    );
  }

  if (!contribution) {
    return (
      <div className="max-w-4xl space-y-6">
        <div
          className="flex items-center gap-3 text-sm"
          style={{ color: "var(--text-muted)" }}
        >
          <Loader2 size={16} className="animate-spin" />
          {loadError ? `Backend indisponível — tentando de novo… (${loadError})` : "Carregando aporte…"}
        </div>
        <div className="animate-pulse h-40 rounded-md" style={{ background: "var(--bg-secondary)" }} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {loadError && (
        <div
          className="max-w-5xl p-3 rounded-md text-xs font-medium"
          style={{ background: "var(--warning-light)", color: "var(--text-secondary)" }}
        >
          Conexão com o backend instável — mostrando o último estado conhecido.
        </div>
      )}
      <AnalysisFlow
        contribution={contribution}
        onPoll={reload}
        onRetry={handleRetry}
        resuming={resuming}
        retryError={retryError}
      />
    </div>
  );
};

export default AporteDetailPage;
