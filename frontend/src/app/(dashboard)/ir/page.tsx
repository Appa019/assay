"use client";

import { useEffect, useState } from "react";
import { CalendarRange, FileCheck, Receipt } from "lucide-react";
import {
  fetchTaxReport,
  type AssetClass,
  type TaxMonthClass,
  type TaxReport,
} from "@/lib/api";
import { formatBRL, parseLocalDate } from "@/lib/format";

const FIRST_SUPPORTED_YEAR = 2020;

const CLASS_LABELS: Record<AssetClass, string> = {
  fixed_income: "RF",
  stocks: "Ações",
  crypto: "Crypto",
};

const formatMonth = (month: string): string => {
  const label = parseLocalDate(`${month}-01`).toLocaleDateString("pt-BR", {
    month: "long",
  });
  return label.charAt(0).toUpperCase() + label.slice(1);
};

/**
 * Tax section. Exported by name so /investimentos can host it as a sub-tab;
 * the default export keeps this route alive for existing deep links.
 */
export const IrView = () => {
  const currentYear = new Date().getFullYear();
  const years = Array.from(
    { length: currentYear - FIRST_SUPPORTED_YEAR + 1 },
    (_, i) => currentYear - i
  );

  const [year, setYear] = useState(currentYear);
  const [report, setReport] = useState<TaxReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Defer to a task so no state update runs synchronously in the effect.
    const timer = setTimeout(() => {
      void (async () => {
        setLoading(true);
        setError(null);
        try {
          const data = await fetchTaxReport(year);
          if (!cancelled) setReport(data);
        } catch (err) {
          if (!cancelled) {
            // 422 (ano fora do intervalo) e afins: mostra o detail do backend.
            setReport(null);
            setError(err instanceof Error ? err.message : "Erro ao carregar o mapa de IR");
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
    }, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [year]);

  const fixedIncomeRows =
    report?.months.flatMap((m) =>
      (m.fixed_income_info ?? []).map((info) => ({ month: m.month, ...info }))
    ) ?? [];

  return (
    <div className="space-y-10 max-w-5xl">
      <header className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between md:gap-6">
        <div>
          <h2
            className="text-4xl md:text-5xl tracking-tight leading-[1.05]"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Imposto de renda
          </h2>
          <p className="text-sm mt-3 max-w-xl" style={{ color: "var(--text-secondary)" }}>
            Mapa simplificado por mês: vendas, isenções e DARF devido em ações e
            crypto nacional, o resultado anual da crypto no exterior e as posições
            de 31/12 para bens e direitos.
          </p>
        </div>
        <div className="flex items-center gap-2 w-full md:w-auto shrink-0">
          <CalendarRange size={15} style={{ color: "var(--text-muted)" }} />
          {/* text-base below md: iOS zooms the viewport on inputs under 16px. */}
          <select
            aria-label="Ano-calendário"
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="flex-1 md:flex-none min-h-11 md:min-h-0 px-4 py-2.5 rounded-md text-base md:text-sm font-semibold outline-none tabular"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </header>

      {error && (
        <div
          className="p-4 rounded-md text-sm"
          style={{ background: "var(--danger-light)", color: "var(--danger)" }}
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-4">
          <div className="animate-pulse h-24 rounded-md" style={{ background: "var(--bg-secondary)" }} />
          <div className="animate-pulse h-48 rounded-md" style={{ background: "var(--bg-secondary)" }} />
        </div>
      ) : report ? (
        <>
          <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div
              className="p-6 rounded-md"
              style={{
                background:
                  report.total_darf_brl > 0 ? "var(--warning-light)" : "var(--bg-card)",
                border: `1px solid ${report.total_darf_brl > 0 ? "var(--warning)" : "var(--border)"}`,
              }}
            >
              <p
                className="text-[11px] uppercase tracking-[0.16em] font-medium"
                style={{ color: "var(--text-muted)" }}
              >
                Total DARF em {report.year}
              </p>
              <p
                className="text-3xl mt-3 tracking-tight"
                style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
              >
                {formatBRL(report.total_darf_brl)}
              </p>
              <p className="text-xs mt-1.5" style={{ color: "var(--text-muted)" }}>
                {report.total_darf_brl > 0
                  ? "soma dos meses com imposto devido"
                  : "nenhum imposto devido no ano"}
              </p>
            </div>
            <StatCard
              title="Prejuízo a compensar · Ações"
              value={formatBRL(report.loss_carryforward_brl.stocks)}
              sub="abate ganhos futuros da mesma classe"
            />
            <StatCard
              title="Crypto no exterior · imposto do ano"
              value={formatBRL(report.crypto_abroad.tax_due_brl)}
              sub={
                report.crypto_abroad.loss_carryforward_brl > 0
                  ? `15% na ${report.crypto_abroad.paid_in}; prejuízo a compensar ${formatBRL(report.crypto_abroad.loss_carryforward_brl)}`
                  : `15% sobre o resultado do ano, na ${report.crypto_abroad.paid_in}`
              }
            />
          </section>

          {report.months.length === 0 ? (
            <div
              className="text-center py-16 rounded-md"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <FileCheck
                size={36}
                className="mx-auto mb-4"
                style={{ color: "var(--border-strong)" }}
              />
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                Sem vendas em {report.year}
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Nenhuma apuração mensal: não há DARF a pagar neste ano
              </p>
            </div>
          ) : (
            <section className="space-y-4">
              <h3
                className="text-2xl tracking-tight flex items-center gap-2.5"
                style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
              >
                <Receipt size={18} style={{ color: "var(--text-muted)" }} />
                Apuração mensal
              </h3>
              <div
                className="rounded-md overflow-hidden"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                {/* Phone: one stacked block per month — five columns are
                    unreadable at 390px. */}
                <div className="md:hidden">
                  {report.months.map((m, idx) => (
                    <div
                      key={m.month}
                      className="px-4 py-4 space-y-4"
                      style={
                        idx > 0 ? { borderTop: "1px solid var(--border)" } : undefined
                      }
                    >
                      <p
                        className="text-sm font-semibold"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {formatMonth(m.month)}
                      </p>
                      <MonthClassBlock label="Vendas ações" cls={m.stocks} />
                      <MonthClassBlock
                        label="Vendas crypto nacional"
                        cls={m.crypto}
                        lossCarries={false}
                      />
                    </div>
                  ))}
                </div>
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr
                        className="text-left text-[10px] uppercase tracking-[0.16em]"
                        style={{
                          color: "var(--text-muted)",
                          borderBottom: "1px solid var(--border)",
                        }}
                      >
                        <th className="px-4 py-3 font-medium">Mês</th>
                        <th className="px-4 py-3 font-medium text-right">Vendas ações</th>
                        <th className="px-4 py-3 font-medium">Status ações</th>
                        <th className="px-4 py-3 font-medium text-right">Vendas crypto BR</th>
                        <th className="px-4 py-3 font-medium">Status crypto BR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.months.map((m) => (
                        <tr key={m.month} style={{ borderBottom: "1px solid var(--border)" }}>
                          <td
                            className="px-4 py-3.5 font-medium"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {formatMonth(m.month)}
                          </td>
                          <td className="px-4 py-3.5 text-right tabular">
                            {m.stocks.sales_brl > 0 ? formatBRL(m.stocks.sales_brl) : "–"}
                          </td>
                          <td className="px-4 py-3.5">
                            <TaxStatus cls={m.stocks} />
                          </td>
                          <td className="px-4 py-3.5 text-right tabular">
                            {m.crypto.sales_brl > 0 ? formatBRL(m.crypto.sales_brl) : "–"}
                          </td>
                          <td className="px-4 py-3.5">
                            <TaxStatus cls={m.crypto} lossCarries={false} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {fixedIncomeRows.length > 0 && (
            <section className="space-y-3">
              <div>
                <h3
                  className="text-xl tracking-tight"
                  style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
                >
                  Renda fixa · IR retido na fonte
                </h3>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  Informativo: o imposto do CDB é retido pelo banco na tabela
                  regressiva, sem DARF a emitir.
                </p>
              </div>
              <div
                className="rounded-md overflow-hidden"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                {/* Phone: stacked block per lançamento. */}
                <div className="md:hidden">
                  {fixedIncomeRows.map((row, idx) => (
                    <div
                      key={`m-${row.month}-${row.ticker}-${idx}`}
                      className="px-4 py-4"
                      style={
                        idx > 0 ? { borderTop: "1px solid var(--border)" } : undefined
                      }
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <p
                          className="text-sm font-semibold min-w-0 break-words"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {row.ticker}
                        </p>
                        <p
                          className="text-xs shrink-0"
                          style={{ color: "var(--text-muted)" }}
                        >
                          {formatMonth(row.month)}
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-3 mt-3">
                        <StackedField
                          label="Rendimento"
                          value={formatBRL(row.income_brl)}
                        />
                        <StackedField
                          label="Dias"
                          value={row.days_held !== null ? String(row.days_held) : "–"}
                        />
                        <StackedField
                          label="Alíquota retida"
                          value={
                            row.withheld_rate_pct !== null
                              ? `${row.withheld_rate_pct.toFixed(1)}%`
                              : "–"
                          }
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr
                        className="text-left text-[10px] uppercase tracking-[0.16em]"
                        style={{
                          color: "var(--text-muted)",
                          borderBottom: "1px solid var(--border)",
                        }}
                      >
                        <th className="px-4 py-3 font-medium">Mês</th>
                        <th className="px-4 py-3 font-medium">Título</th>
                        <th className="px-4 py-3 font-medium text-right">Rendimento</th>
                        <th className="px-4 py-3 font-medium text-right">Dias</th>
                        <th className="px-4 py-3 font-medium text-right">Alíquota retida</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fixedIncomeRows.map((row, idx) => (
                        <tr
                          key={`${row.month}-${row.ticker}-${idx}`}
                          style={{ borderBottom: "1px solid var(--border)" }}
                        >
                          <td className="px-4 py-3">{formatMonth(row.month)}</td>
                          <td
                            className="px-4 py-3 font-medium"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {row.ticker}
                          </td>
                          <td className="px-4 py-3 text-right tabular">
                            {formatBRL(row.income_brl)}
                          </td>
                          <td className="px-4 py-3 text-right tabular">
                            {row.days_held ?? "–"}
                          </td>
                          <td className="px-4 py-3 text-right tabular">
                            {row.withheld_rate_pct !== null
                              ? `${row.withheld_rate_pct.toFixed(1)}%`
                              : "–"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {report.year_end_positions.length > 0 && (
            <section className="space-y-3">
              <div>
                <h3
                  className="text-xl tracking-tight"
                  style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
                >
                  Posições em 31/12/{report.year}
                </h3>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  Base para a ficha de bens e direitos, pelo custo de aquisição.
                </p>
              </div>
              <div
                className="rounded-md overflow-hidden"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              >
                {/* Phone: stacked block per posição. */}
                <div className="md:hidden">
                  {report.year_end_positions.map((pos, idx) => (
                    <div
                      key={`m-${pos.ticker}-${idx}`}
                      className="px-4 py-4"
                      style={
                        idx > 0 ? { borderTop: "1px solid var(--border)" } : undefined
                      }
                    >
                      <div className="flex items-center gap-2 flex-wrap">
                        <p
                          className="text-sm font-semibold min-w-0 break-words"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {pos.ticker}
                        </p>
                        <span
                          className="text-xs px-2 py-0.5 rounded font-medium"
                          style={{
                            background: "var(--bg-secondary)",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {CLASS_LABELS[pos.asset_class]}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-3 mt-3">
                        <StackedField
                          label="Quantidade"
                          value={pos.quantity.toLocaleString("pt-BR", {
                            maximumFractionDigits: 8,
                          })}
                        />
                        <StackedField
                          label="Custo de aquisição"
                          value={formatBRL(pos.cost_basis_brl)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr
                        className="text-left text-[10px] uppercase tracking-[0.16em]"
                        style={{
                          color: "var(--text-muted)",
                          borderBottom: "1px solid var(--border)",
                        }}
                      >
                        <th className="px-4 py-3 font-medium">Ativo</th>
                        <th className="px-4 py-3 font-medium">Classe</th>
                        <th className="px-4 py-3 font-medium text-right">Quantidade</th>
                        <th className="px-4 py-3 font-medium text-right">Custo de aquisição</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.year_end_positions.map((pos, idx) => (
                        <tr
                          key={`${pos.ticker}-${idx}`}
                          style={{ borderBottom: "1px solid var(--border)" }}
                        >
                          <td
                            className="px-4 py-3 font-semibold"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {pos.ticker}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className="text-xs px-2 py-0.5 rounded font-medium"
                              style={{
                                background: "var(--bg-secondary)",
                                color: "var(--text-secondary)",
                              }}
                            >
                              {CLASS_LABELS[pos.asset_class]}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right tabular">
                            {pos.quantity.toLocaleString("pt-BR", {
                              maximumFractionDigits: 8,
                            })}
                          </td>
                          <td
                            className="px-4 py-3 text-right tabular font-semibold"
                            style={{ color: "var(--text-primary)" }}
                          >
                            {formatBRL(pos.cost_basis_brl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {report.notes.length > 0 && (
            <footer
              className="pt-5 space-y-1.5"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {report.notes.map((note, idx) => (
                <p
                  key={idx}
                  className="text-[11px] leading-relaxed"
                  style={{ color: "var(--text-muted)" }}
                >
                  {note}
                </p>
              ))}
            </footer>
          )}
        </>
      ) : null}
    </div>
  );
};

const StatCard = ({
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

/** Label above value — the phone replacement for a table cell. */
const StackedField = ({ label, value }: { label: string; value: string }) => (
  <div className="min-w-0">
    <p
      className="text-[10px] uppercase tracking-[0.16em] font-medium"
      style={{ color: "var(--text-muted)" }}
    >
      {label}
    </p>
    <p
      className="text-sm mt-1 tabular break-words"
      style={{ color: "var(--text-primary)" }}
    >
      {value}
    </p>
  </div>
);

/** Phone view of one month × one asset class: sales figure plus the status. */
const MonthClassBlock = ({
  label,
  cls,
  lossCarries = true,
}: {
  label: string;
  cls: TaxMonthClass;
  lossCarries?: boolean;
}) => (
  <div>
    <StackedField
      label={label}
      value={cls.sales_brl > 0 ? formatBRL(cls.sales_brl) : "–"}
    />
    <div className="mt-2">
      <TaxStatus cls={cls} lossCarries={lossCarries} />
    </div>
  </div>
);

/** lossCarries=false for national crypto: a loss there offsets nothing (P&R 583). */
const TaxStatus = ({ cls, lossCarries = true }: { cls: TaxMonthClass; lossCarries?: boolean }) => {
  if (cls.sales_brl <= 0) {
    return (
      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
        –
      </span>
    );
  }

  const carryNote =
    cls.loss_carry_used_brl > 0 ? (
      <span className="block text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
        compensou {formatBRL(cls.loss_carry_used_brl)}
      </span>
    ) : null;

  if (cls.exempt) {
    return (
      <span>
        <Badge bg="var(--success-light)" color="var(--success)">
          Isento
        </Badge>
        {carryNote}
      </span>
    );
  }
  if (cls.tax_due_brl > 0) {
    return (
      <span>
        <Badge
          bg={cls.darf_below_minimum ? "var(--bg-secondary)" : "var(--danger-light)"}
          color={cls.darf_below_minimum ? "var(--text-secondary)" : "var(--danger)"}
        >
          DARF {formatBRL(cls.tax_due_brl)}
          {cls.darf_below_minimum ? " · abaixo do mínimo" : ""}
        </Badge>
        {carryNote}
      </span>
    );
  }
  if (cls.net_gain_brl < 0) {
    return (
      <span>
        <Badge bg="var(--bg-secondary)" color="var(--text-secondary)">
          {lossCarries ? "Prejuízo (compensável)" : "Prejuízo (não compensa)"}
        </Badge>
        {carryNote}
      </span>
    );
  }
  return (
    <span>
      <Badge bg="var(--bg-secondary)" color="var(--text-secondary)">
        Sem DARF
      </Badge>
      {carryNote}
    </span>
  );
};

const Badge = ({
  bg,
  color,
  children,
}: {
  bg: string;
  color: string;
  children: React.ReactNode;
}) => (
  <span
    className="inline-block text-[11px] font-semibold px-2 py-0.5 rounded tabular"
    style={{ background: bg, color }}
  >
    {children}
  </span>
);

export default IrView;
