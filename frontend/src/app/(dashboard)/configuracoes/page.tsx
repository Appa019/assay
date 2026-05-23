"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

type Health = { status: string; version: string } | null;

const ConfiguracoesPage = () => {
  const [health, setHealth] = useState<Health>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        if (!res.ok) throw new Error(`status ${res.status}`);
        setHealth(await res.json());
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro");
      }
    };
    void load();
  }, []);

  return (
    <div className="space-y-10 max-w-3xl">
      <header>
        <h2
          className="text-5xl tracking-tight leading-[1.05]"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Ajustes
        </h2>
        <p className="text-sm mt-3" style={{ color: "var(--text-secondary)" }}>
          Configurações leem do <code>.env</code> do backend. Edite o arquivo e reinicie.
        </p>
      </header>

      <section
        className="p-6 rounded-md space-y-3"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3
          className="text-xl tracking-tight"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Backend
        </h3>
        <Row label="API base" value={API_BASE} />
        <Row label="Health" value={health ? `${health.status} · v${health.version}` : error ?? "..."} />
      </section>

      <section
        className="p-6 rounded-md space-y-3"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3
          className="text-xl tracking-tight"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Variáveis de ambiente
        </h3>
        <ul className="text-xs space-y-2" style={{ color: "var(--text-secondary)" }}>
          <Var name="SQLITE_PATH" desc="caminho do arquivo SQLite" />
          <Var name="TARGET_FIXED_INCOME" desc="meta de RF (0.35 = 35%)" />
          <Var name="TARGET_STOCKS" desc="meta de Ações (0.40)" />
          <Var name="TARGET_CRYPTO" desc="meta de Crypto (0.25)" />
          <Var name="CONTRIBUTION_INTERVAL_DAYS" desc="dias entre aportes (default 30)" />
          <Var name="COINGECKO_API_URL" desc="endpoint CoinGecko" />
          <Var name="COINGECKO_API_KEY" desc="opcional, se tiver Pro key" />
        </ul>
      </section>

      <section
        className="p-6 rounded-md"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3
          className="text-xl tracking-tight mb-3"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Como rodar o ciclo do comitê
        </h3>
        <ol
          className="text-sm space-y-2 list-decimal list-inside"
          style={{ color: "var(--text-secondary)" }}
        >
          <li>Abra um terminal limpo (sem contexto prévio).</li>
          <li>
            Rode{" "}
            <code style={{ background: "var(--bg-secondary)", padding: "1px 6px", borderRadius: 3 }}>
              claude --dangerously-skip-permissions
            </code>{" "}
            com Opus 4.7 + max reasoning.
          </li>
          <li>Volte aqui, abra &quot;Novo aporte&quot;, informe o valor e gere os 3 prompts.</li>
          <li>Cole prompt 1 → cole resposta → cole prompt 2 → cole resposta → cole prompt 3 → finalize.</li>
        </ol>
      </section>
    </div>
  );
};

const Row = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between text-sm">
    <span style={{ color: "var(--text-muted)" }}>{label}</span>
    <code
      className="font-mono"
      style={{ color: "var(--text-primary)" }}
    >
      {value}
    </code>
  </div>
);

const Var = ({ name, desc }: { name: string; desc: string }) => (
  <li className="flex items-baseline gap-2">
    <code
      className="font-mono shrink-0"
      style={{ color: "var(--text-primary)", background: "var(--bg-secondary)", padding: "1px 6px", borderRadius: 3 }}
    >
      {name}
    </code>
    <span>— {desc}</span>
  </li>
);

export default ConfiguracoesPage;
