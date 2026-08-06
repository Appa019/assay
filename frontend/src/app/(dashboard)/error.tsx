"use client";

import { RefreshCw } from "lucide-react";

/**
 * Without this, a client-side exception renders Next's bare "Application error"
 * on a blank page. On a phone there is no console to open, so the screen has to
 * say what happened and offer a way out.
 */
const DashboardError = ({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) => (
  <div
    className="max-w-xl rounded-md border p-6 md:p-8"
    style={{ background: "var(--bg-card)", borderColor: "var(--border)" }}
  >
    <h2
      className="text-2xl md:text-3xl tracking-tight"
      style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
    >
      Algo quebrou nesta tela
    </h2>
    <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
      O resto do app continua funcionando. Use o menu abaixo para sair daqui.
      Se insistir, provavelmente é o backend devolvendo algo inesperado.
    </p>

    <p
      className="mt-4 rounded-md p-3 font-mono text-xs break-words"
      style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
    >
      {error.message || "Erro sem mensagem"}
      {error.digest ? ` · ${error.digest}` : ""}
    </p>

    <button
      type="button"
      onClick={reset}
      className="mt-5 flex min-h-[2.75rem] items-center gap-2 rounded-md px-5 text-sm font-semibold"
      style={{ background: "var(--accent)", color: "white" }}
    >
      <RefreshCw size={14} />
      Tentar de novo
    </button>
  </div>
);

export default DashboardError;
