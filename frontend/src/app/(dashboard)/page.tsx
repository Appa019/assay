"use client";

import Link from "next/link";
import { ArrowRight, RefreshCw, Sparkles, WifiOff } from "lucide-react";
import { usePortfolio } from "@/hooks/use-portfolio";
import { useCadence } from "@/hooks/use-cadence";
import { useMacro } from "@/hooks/use-macro";
import { usePortfolioHistory } from "@/hooks/use-portfolio-history";
import { formatBRLCompact, formatDate } from "@/lib/format";
import {
  AllocationDonut,
  AllocationVsTargetChart,
  EquityCurveChart,
} from "@/components/portfolio-charts";

const DashboardPage = () => {
  const { data: portfolio, loading: pLoading, error: pError, refresh } = usePortfolio();
  const { data: cadence } = useCadence();
  const { data: macro } = useMacro();
  const { data: history } = usePortfolioHistory(365);

  const backendDown = !pLoading && !portfolio && pError !== null;

  return (
    <div className="space-y-12 max-w-6xl">
      <header className="flex items-end justify-between">
        <div>
          <p
            className="text-[11px] uppercase tracking-[0.18em] font-medium mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            {new Date().toLocaleDateString("pt-BR", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </p>
          <h2
            className="text-6xl tracking-tight leading-[1.02]"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Mesa de aportes
          </h2>
          <p
            className="text-base mt-4 max-w-xl leading-relaxed"
            style={{ color: "var(--text-secondary)" }}
          >
            Aporte quando quiser — sem ciclo fixo. O comitê autônomo aloca a
            cada aporte e revisa a carteira toda semana. Decisões ficam no histórico.
          </p>
        </div>
        <Link
          href="/aporte"
          className="flex items-center gap-2 px-5 py-3 rounded-md text-sm font-semibold"
          style={{ background: "var(--accent)", color: "white" }}
        >
          <Sparkles size={14} />
          Novo aporte
          <ArrowRight size={14} />
        </Link>
      </header>

      {backendDown ? (
        <section
          className="p-8 rounded-md flex items-center justify-between gap-6"
          style={{ background: "var(--danger-light)", border: "1px solid var(--danger)" }}
        >
          <div className="flex items-start gap-4">
            <WifiOff size={20} style={{ color: "var(--danger)" }} className="mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Backend indisponível
              </p>
              <p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                Não foi possível carregar a carteira ({pError}). Verifique se o
                backend está rodando (<code>./start.sh</code>) e tente de novo.
              </p>
            </div>
          </div>
          <button
            onClick={() => void refresh()}
            className="flex items-center gap-2 px-4 py-2.5 rounded-md text-sm font-semibold shrink-0"
            style={{ background: "var(--accent)", color: "white" }}
          >
            <RefreshCw size={13} />
            Tentar de novo
          </button>
        </section>
      ) : (
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <SummaryCard
            title="Patrimônio"
            value={pLoading ? "..." : formatBRLCompact(portfolio?.total_value ?? 0)}
            sub={pLoading ? "carregando…" : `${portfolio?.assets.length ?? 0} ativos`}
          />
          <SummaryCard
            title="Alocação atual"
            value={
              pLoading
                ? "..."
                : `${(portfolio?.allocation.fixed_income_pct ?? 0).toFixed(0)} / ${(portfolio?.allocation.stocks_pct ?? 0).toFixed(0)} / ${(portfolio?.allocation.crypto_pct ?? 0).toFixed(0)}`
            }
            sub="RF · Ações · Crypto (%)"
          />
          <SummaryCard
            title="Último aporte"
            value={
              cadence
                ? cadence.days_since_last === null
                  ? "—"
                  : cadence.days_since_last === 0
                    ? "Hoje"
                    : `há ${cadence.days_since_last}d`
                : "..."
            }
            sub={
              cadence?.last_contribution_date
                ? `${formatDate(cadence.last_contribution_date)} · ${cadence.total_contributions} no total`
                : "nenhum ainda · aporte quando quiser"
            }
          />
        </section>
      )}

      {!backendDown && portfolio && (
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard
            title="Alocação vs alvo"
            sub="Percentual atual de cada classe contra a meta do mandato"
          >
            <AllocationVsTargetChart portfolio={portfolio} />
          </ChartCard>
          <ChartCard title="Composição da carteira" sub="Distribuição por classe, em R$">
            <AllocationDonut portfolio={portfolio} />
          </ChartCard>
        </section>
      )}

      {!backendDown && history && history.length > 0 && (
        <ChartCard
          title="Curva de patrimônio"
          sub="Valor total da carteira nos snapshots diários"
        >
          <EquityCurveChart history={history} />
        </ChartCard>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div
          className="p-7 rounded-md"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3
            className="text-2xl tracking-tight mb-4"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Macro de hoje
          </h3>
          {macro ? (
            <dl className="space-y-2.5 text-sm">
              <Row label="Selic" value={fmt(macro.macro.selic, "% a.a.")} />
              <Row label="IPCA 12m" value={fmt(macro.macro.ipca_12m, "%")} />
              <Row label="CDI" value={fmt(macro.macro.cdi, "% a.a.")} />
              <Row label="USD/BRL" value={fmt(macro.macro.usd_brl, "", "R$ ")} />
              <Row label="Ibovespa" value={fmt(macro.ibovespa.level, " pts")} />
              <Row label="BTC dominance" value={fmt(macro.crypto_global.btc_dominance, "%")} />
              <Row label="Fear & Greed" value={macro.fear_greed_index?.toString() ?? "—"} />
            </dl>
          ) : (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              Capturando dados...
            </p>
          )}
        </div>

        <div
          className="p-7 rounded-md"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3
            className="text-2xl tracking-tight mb-4"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Desvio do mandato
          </h3>
          {portfolio ? (
            <div className="space-y-4">
              <AllocBar
                label="Renda fixa"
                actual={portfolio.allocation.fixed_income_pct}
                target={portfolio.target_allocation.fixed_income}
                deviation={portfolio.deviation.fixed_income}
              />
              <AllocBar
                label="Ações"
                actual={portfolio.allocation.stocks_pct}
                target={portfolio.target_allocation.stocks}
                deviation={portfolio.deviation.stocks}
              />
              <AllocBar
                label="Crypto"
                actual={portfolio.allocation.crypto_pct}
                target={portfolio.target_allocation.crypto}
                deviation={portfolio.deviation.crypto}
              />
            </div>
          ) : (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              {backendDown ? "Sem dados — backend fora do ar" : "..."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
};

const ChartCard = ({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: React.ReactNode;
}) => (
  <div
    className="p-7 rounded-md"
    style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
  >
    <h3
      className="text-2xl tracking-tight"
      style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
    >
      {title}
    </h3>
    <p className="text-xs mt-1 mb-5" style={{ color: "var(--text-muted)" }}>
      {sub}
    </p>
    {children}
  </div>
);

const SummaryCard = ({
  title,
  value,
  sub,
}: {
  title: string;
  value: string;
  sub: string;
}) => (
  <div
    className="p-6 rounded-md"
    style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
  >
    <p
      className="text-[11px] uppercase tracking-[0.16em] font-medium"
      style={{ color: "var(--text-muted)" }}
    >
      {title}
    </p>
    <p
      className="text-3xl mt-3 tracking-tight"
      style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
    >
      {value}
    </p>
    <p className="text-xs mt-1.5" style={{ color: "var(--text-muted)" }}>
      {sub}
    </p>
  </div>
);

const AllocBar = ({
  label,
  actual,
  target,
  deviation,
}: {
  label: string;
  actual: number;
  target: number;
  deviation: number;
}) => (
  <div>
    <div className="flex items-center justify-between text-xs mb-1.5">
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span className="tabular" style={{ color: "var(--text-primary)" }}>
        {actual.toFixed(1)}% / alvo {target.toFixed(0)}%{" "}
        <span
          style={{ color: Math.abs(deviation) > 5 ? "var(--warning)" : "var(--text-muted)" }}
          className="font-medium ml-2"
        >
          ({deviation > 0 ? "+" : ""}
          {deviation.toFixed(1)} pp)
        </span>
      </span>
    </div>
    <div
      className="h-1.5 rounded-full overflow-hidden relative"
      style={{ background: "var(--bg-secondary)" }}
    >
      <div
        className="h-full"
        style={{
          width: `${Math.min(actual, 100)}%`,
          background: "var(--accent)",
        }}
      />
      <div
        className="absolute top-0 bottom-0 w-px"
        style={{ left: `${Math.min(target, 100)}%`, background: "var(--text-secondary)" }}
      />
    </div>
  </div>
);

const Row = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between">
    <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
    <dd
      className="tabular font-semibold"
      style={{ color: "var(--text-primary)" }}
    >
      {value}
    </dd>
  </div>
);

const fmt = (value: number | null | undefined, suffix = "", prefix = "") => {
  if (value === null || value === undefined) return "—";
  return `${prefix}${value.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}${suffix}`;
};

export default DashboardPage;
