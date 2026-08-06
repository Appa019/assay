"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

type Health = { status: string; version: string } | null;

const ConfiguracoesPage = () => {
  const [health, setHealth] = useState<Health>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        if (!res.ok) throw new Error(`status ${res.status}`);
        const body = (await res.json()) as Health; // own API — shape is ours
        if (!cancelled) setHealth(body);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Erro");
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-10 max-w-3xl">
      <header>
        <h2
          className="text-[2rem] md:text-5xl tracking-tight leading-[1.06]"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Ajustes
        </h2>
        <p className="text-sm mt-3" style={{ color: "var(--text-secondary)" }}>
          Configurações leem do <code>.env</code> do backend. Edite o arquivo e reinicie.
        </p>
      </header>

      <section
        className="p-5 md:p-6 rounded-md space-y-3"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3
          className="text-xl tracking-tight"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Backend
        </h3>
        {/* Empty base means the Next server proxies /api itself, which is how
            the app is served behind a single TLS front. */}
        <Row label="API base" value={API_BASE || "mesma origem (proxy do Next)"} />
        <Row label="Health" value={health ? `${health.status} · v${health.version}` : error ?? "..."} />
      </section>

      <section
        className="p-5 md:p-6 rounded-md space-y-3"
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
          <Var name="MIN_HOLDING_DAYS" desc="trava de venda por lote, ações/crypto (default 30)" />
          <Var name="AGENT_MODEL" desc="modelo do comitê (default opus)" />
          <Var name="AGENT_EFFORT" desc="reasoning do comitê (default max)" />
          <Var name="COINGECKO_API_URL" desc="endpoint CoinGecko" />
          <Var name="COINGECKO_API_KEY" desc="opcional, se tiver Pro key" />
          <Var name="TELEGRAM_BOT_TOKEN" desc="token do @BotFather (não commitar)" />
          <Var name="TELEGRAM_CHAT_ID" desc="preenchido pelo telegram_setup.py" />
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
          Como rodar o comitê
        </h3>
        <ol
          className="text-sm space-y-2 list-decimal list-inside"
          style={{ color: "var(--text-secondary)" }}
        >
          <li>
            Em <strong>Aporte</strong>, informe o valor e clique em &quot;Adicionar aporte e rodar
            análise&quot;.
          </li>
          <li>
            O agente roda todas as reuniões encadeadas no <code style={{ background: "var(--bg-secondary)", padding: "1px 6px", borderRadius: 3 }}>claude</code>{" "}
            headless (Opus · max): acompanhe etapa por etapa na própria tela.
          </li>
          <li>Ao final, ele entrega onde investir e quanto; a folha de ordens também chega no Telegram.</li>
          <li>Registre o que comprou em <strong>Ativos</strong> (cada compra é um lote com trava própria).</li>
        </ol>
      </section>
    </div>
  );
};

const Row = ({ label, value }: { label: string; value: string }) => (
  <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-sm">
    <span className="shrink-0" style={{ color: "var(--text-muted)" }}>
      {label}
    </span>
    <code
      className="font-mono break-all text-right"
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
    <span>· {desc}</span>
  </li>
);

export default ConfiguracoesPage;
