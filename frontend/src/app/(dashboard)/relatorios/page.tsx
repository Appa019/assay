"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowUpRight,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  FileBarChart,
  Trash2,
  Unlock,
} from "lucide-react";
import {
  deleteContribution,
  fetchContribution,
  fetchReport,
  listContributions,
  listReports,
  type Contribution,
  type ContributionListItem,
  type Prompt,
  type ReportListItem,
  type ReportRead,
} from "@/lib/api";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { formatDateLong, formatDateTime, stripMachineBlocks } from "@/lib/format";

const RelatoriosPage = () => {
  const [items, setItems] = useState<ContributionListItem[]>([]);
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Details cached by id: out-of-order responses can never render under the
  // wrong item, and revisiting an item is instant.
  const [details, setDetails] = useState<Record<string, Contribution>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [contribs, reps] = await Promise.all([listContributions(), listReports()]);
      setItems(contribs);
      setReports(reps);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar histórico");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleExpand = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (details[id]) return;
    try {
      const detail = await fetchContribution(id);
      // Key by the response's own id — a late response for another item
      // fills its own slot instead of clobbering the active one.
      setDetails((prev) => ({ ...prev, [detail.id]: detail }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Apagar este aporte e todas as respostas?")) return;
    try {
      await deleteContribution(id);
      if (expandedId === id) setExpandedId(null);
      setDetails((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao apagar");
    }
  };

  return (
    <div className="space-y-10 max-w-5xl">
      <header>
        <h2
          className="text-5xl tracking-tight leading-[1.05]"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Histórico
        </h2>
        <p className="text-sm mt-3" style={{ color: "var(--text-secondary)" }}>
          Todos os aportes analisados e os relatórios do comitê. Clique para
          revisitar as reuniões e as folhas de ordens.
        </p>
      </header>

      {error && (
        <div
          className="p-4 rounded-md text-sm"
          style={{ background: "var(--danger-light)", color: "var(--danger)" }}
        >
          {error}
        </div>
      )}

      <AgentReports reports={reports} />

      <div>
        <h3
          className="text-xl tracking-tight mb-4"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          Aportes
        </h3>
      </div>

      {loading ? (
        <div
          className="animate-pulse h-32 rounded-md"
          style={{ background: "var(--bg-secondary)" }}
        />
      ) : items.length === 0 ? (
        <div
          className="text-center py-20 rounded-md"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <FileBarChart
            size={36}
            className="mx-auto mb-4"
            style={{ color: "var(--border-strong)" }}
          />
          <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
            Nenhum aporte registrado
          </p>
          <Link
            href="/aporte"
            className="inline-flex items-center gap-2 mt-5 px-5 py-2.5 rounded-md text-sm font-semibold"
            style={{ background: "var(--accent)", color: "white" }}
          >
            Fazer o primeiro aporte
            <ChevronRight size={13} />
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const expanded = expandedId === item.id;
            const detail = details[item.id];
            const tone =
              item.status === "completed"
                ? "var(--success)"
                : item.status === "in_progress"
                  ? "var(--accent)"
                  : "var(--text-muted)";
            return (
              <motion.article
                key={item.id}
                layout
                className="rounded-md overflow-hidden"
                style={{
                  background: "var(--bg-card)",
                  border: `1px solid ${expanded ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                <header
                  className="px-6 py-4 flex items-center justify-between cursor-pointer"
                  onClick={() => void handleExpand(item.id)}
                >
                  <div className="flex items-center gap-5">
                    <div>
                      <p
                        className="text-xs uppercase tracking-[0.16em] font-medium"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {formatDateLong(item.created_at)}
                      </p>
                      <p
                        className="text-2xl tracking-tight mt-1 tabular"
                        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
                      >
                        R${" "}
                        {item.amount_brl.toLocaleString("pt-BR", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </p>
                    </div>
                    <span
                      className="text-[11px] font-medium px-2.5 py-1 rounded-md"
                      style={{ background: "var(--bg-secondary)", color: tone }}
                    >
                      {item.status === "completed"
                        ? "Concluído"
                        : item.status === "in_progress"
                          ? `Em curso ${item.prompts_answered}/${item.prompts_total}`
                          : "Aberto"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/aporte/${item.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-md"
                      style={{ background: "var(--bg-secondary)", color: "var(--accent-strong)" }}
                      title="Abrir a página da análise (acompanhar ou reler)"
                    >
                      <ArrowUpRight size={12} />
                      Abrir análise
                    </Link>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDelete(item.id);
                      }}
                      className="p-2 rounded-md transition-colors"
                      style={{ color: "var(--text-muted)" }}
                      title="Apagar aporte"
                    >
                      <Trash2 size={14} />
                    </button>
                    {expanded ? (
                      <ChevronUp size={18} style={{ color: "var(--text-muted)" }} />
                    ) : (
                      <ChevronDown size={18} style={{ color: "var(--text-muted)" }} />
                    )}
                  </div>
                </header>
                {expanded && (
                  <div
                    className="px-6 py-5"
                    style={{ borderTop: "1px solid var(--border)" }}
                  >
                    {detail ? (
                      <DetailView contribution={detail} />
                    ) : (
                      <div
                        className="animate-pulse h-24 rounded"
                        style={{ background: "var(--bg-secondary)" }}
                      />
                    )}
                  </div>
                )}
              </motion.article>
            );
          })}
        </div>
      )}
    </div>
  );
};

const AgentReports = ({ reports }: { reports: ReportListItem[] }) => {
  const [openId, setOpenId] = useState<string | null>(null);
  // Same stale-response guard as the contributions list: cache by id.
  const [fullById, setFullById] = useState<Record<string, ReportRead>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  const toggle = async (id: string) => {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    setLoadError(null);
    if (fullById[id]) return;
    try {
      const full = await fetchReport(id);
      setFullById((prev) => ({ ...prev, [full.id]: full }));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Erro ao carregar relatório");
    }
  };

  if (reports.length === 0) return null;

  return (
    <section className="space-y-3">
      <h3
        className="text-xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Relatórios do comitê
      </h3>
      <p className="text-xs -mt-1" style={{ color: "var(--text-muted)" }}>
        Revisões semanais e análises de maturidade — também consultadas nos aportes.
      </p>
      <div className="space-y-2">
        {reports.map((r) => {
          const open = openId === r.id;
          const full = fullById[r.id];
          const weekly = r.kind === "weekly";
          return (
            <article
              key={r.id}
              className="rounded-md overflow-hidden"
              style={{
                background: "var(--bg-card)",
                border: `1px solid ${open ? "var(--accent)" : "var(--border)"}`,
              }}
            >
              <header
                className="px-5 py-3.5 flex items-center justify-between cursor-pointer"
                onClick={() => void toggle(r.id)}
              >
                <div className="flex items-center gap-3">
                  {weekly ? (
                    <CalendarClock size={16} style={{ color: "var(--accent-strong)" }} />
                  ) : (
                    <Unlock size={16} style={{ color: "var(--success)" }} />
                  )}
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                      {r.title}
                    </p>
                    <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                      {formatDateTime(r.created_at)} ·{" "}
                      {weekly ? "Semanal" : "Maturidade"} · US$ {r.cost_usd.toFixed(2)}
                    </p>
                  </div>
                </div>
                {open ? (
                  <ChevronUp size={16} style={{ color: "var(--text-muted)" }} />
                ) : (
                  <ChevronDown size={16} style={{ color: "var(--text-muted)" }} />
                )}
              </header>
              {open && (
                <div className="px-5 py-4" style={{ borderTop: "1px solid var(--border)" }}>
                  {full ? (
                    <MarkdownViewer content={full.content} maxHeight={560} />
                  ) : loadError ? (
                    <p className="text-xs" style={{ color: "var(--danger)" }}>
                      {loadError}
                    </p>
                  ) : (
                    <div
                      className="animate-pulse h-20 rounded"
                      style={{ background: "var(--bg-secondary)" }}
                    />
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
};

const DetailView = ({ contribution }: { contribution: Contribution }) => {
  const [activeKey, setActiveKey] = useState<Prompt["prompt_key"]>(
    contribution.prompts[0]?.prompt_key ?? "macro"
  );
  const active = contribution.prompts.find((p) => p.prompt_key === activeKey);
  const macro = contribution.macro_snapshot as
    | { macro?: { selic?: number; ipca_12m?: number; cdi?: number; usd_brl?: number } }
    | null;

  return (
    <div className="space-y-5">
      {macro?.macro && (
        <div
          className="p-4 rounded-md text-xs"
          style={{ background: "var(--bg-secondary)" }}
        >
          <p
            className="text-[10px] uppercase tracking-[0.16em] font-medium mb-2"
            style={{ color: "var(--text-muted)" }}
          >
            Snapshot macro injetado
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 tabular">
            <p>
              <span style={{ color: "var(--text-muted)" }}>Selic </span>
              <strong>{macro.macro.selic ?? "—"}%</strong>
            </p>
            <p>
              <span style={{ color: "var(--text-muted)" }}>IPCA 12m </span>
              <strong>{macro.macro.ipca_12m ?? "—"}%</strong>
            </p>
            <p>
              <span style={{ color: "var(--text-muted)" }}>CDI </span>
              <strong>{macro.macro.cdi ?? "—"}%</strong>
            </p>
            <p>
              <span style={{ color: "var(--text-muted)" }}>USD/BRL </span>
              <strong>R$ {macro.macro.usd_brl ?? "—"}</strong>
            </p>
          </div>
        </div>
      )}

      <div className="flex gap-1.5 flex-wrap">
        {contribution.prompts.map((p) => (
          <button
            key={p.id}
            onClick={() => setActiveKey(p.prompt_key)}
            className="px-3 py-1.5 rounded-md text-xs font-medium"
            style={{
              background:
                activeKey === p.prompt_key ? "var(--accent)" : "var(--bg-secondary)",
              color:
                activeKey === p.prompt_key ? "white" : "var(--text-secondary)",
            }}
          >
            #{p.prompt_order} {p.title.replace(/^Reunião nº \d+ — /, "")}
          </button>
        ))}
      </div>

      {active && (
        <div className="space-y-4">
          <details>
            <summary
              className="cursor-pointer text-[11px] uppercase tracking-[0.16em] font-medium"
              style={{ color: "var(--text-muted)" }}
            >
              Ver prompt enviado
            </summary>
            <pre
              className="mt-3 p-4 rounded-md text-[12px] leading-relaxed whitespace-pre-wrap font-mono max-h-96 overflow-auto"
              style={{
                background: "var(--bg-secondary)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
            >
              {active.content}
            </pre>
          </details>
          <div>
            <p
              className="text-[11px] uppercase tracking-[0.16em] font-medium mb-2"
              style={{ color: "var(--text-muted)" }}
            >
              Resposta do comitê
            </p>
            {active.response ? (
              <div
                className="p-4 rounded-md"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                <MarkdownViewer content={active.response} maxHeight={480} />
              </div>
            ) : (
              <p
                className="text-sm italic"
                style={{ color: "var(--text-muted)" }}
              >
                Sem resposta ainda — reunião não concluída
              </p>
            )}
          </div>
        </div>
      )}

      {contribution.final_summary && (
        <div
          className="p-5 rounded-md"
          style={{ background: "var(--accent-light)", border: "1px solid var(--accent)" }}
        >
          <p
            className="text-[11px] uppercase tracking-[0.16em] font-medium mb-3"
            style={{ color: "var(--accent-strong)" }}
          >
            Resumo executivo
          </p>
          <MarkdownViewer content={stripMachineBlocks(contribution.final_summary)} withToc={false} />
        </div>
      )}

      <Link
        href={`/aporte/${contribution.id}`}
        className="inline-flex items-center gap-1.5 text-xs font-medium"
        style={{ color: "var(--accent)" }}
      >
        Abrir a página completa da análise
        <ChevronRight size={12} />
      </Link>
    </div>
  );
};

export default RelatoriosPage;
