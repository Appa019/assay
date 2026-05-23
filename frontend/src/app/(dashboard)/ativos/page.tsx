"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plus,
  Minus,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  PackageOpen,
  DollarSign,
  Pencil,
} from "lucide-react";
import {
  createAsset,
  deleteAsset,
  sellAsset,
  updateAsset,
  type Asset,
  type AssetClass,
  type AssetCreate,
  type SaleResult,
} from "@/lib/api";
import { usePortfolio } from "@/hooks/use-portfolio";
import { formatBRL, formatNumber } from "@/lib/format";

const ASSET_CLASSES: { value: AssetClass; label: string }[] = [
  { value: "fixed_income", label: "Renda Fixa" },
  { value: "stocks", label: "Ações" },
  { value: "crypto", label: "Crypto" },
];

const CLASS_LABELS: Record<AssetClass, string> = {
  fixed_income: "RF",
  stocks: "Ações",
  crypto: "Crypto",
};

const FILTER_TABS = [
  { value: "all", label: "Todos" },
  { value: "stocks", label: "Ações" },
  { value: "crypto", label: "Crypto" },
  { value: "fixed_income", label: "Renda Fixa" },
] as const;

type SortField =
  | "ticker"
  | "asset_class"
  | "quantity"
  | "avg_price"
  | "current_price"
  | "pnl"
  | "total_value";

type SortDirection = "asc" | "desc";

const AtivosPage = () => {
  const { data, loading, refresh } = usePortfolio();
  const [showBuyForm, setShowBuyForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [sellTarget, setSellTarget] = useState<Asset | null>(null);
  const [lastSale, setLastSale] = useState<SaleResult | null>(null);
  const [formData, setFormData] = useState<Partial<AssetCreate>>({
    asset_class: "stocks",
  });
  const [editPrice, setEditPrice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);
  const [filter, setFilter] = useState<string>("all");
  const [sortField, setSortField] = useState<SortField>("total_value");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const sellDialog = useRef<HTMLDialogElement>(null);
  const editDialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (sellTarget) sellDialog.current?.showModal();
    else sellDialog.current?.close();
  }, [sellTarget]);

  useEffect(() => {
    if (editing) {
      setEditPrice(String(editing.current_price ?? editing.avg_price));
      editDialog.current?.showModal();
    } else {
      editDialog.current?.close();
    }
  }, [editing]);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message]);

  const handleSort = (field: SortField) => {
    if (field === sortField) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const rows = useMemo(() => {
    const assets = data?.assets ?? [];
    const filtered =
      filter === "all"
        ? assets
        : assets.filter((a) => a.asset_class === filter);

    return [...filtered].sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      const priceA = a.current_price ?? a.avg_price;
      const priceB = b.current_price ?? b.avg_price;
      switch (sortField) {
        case "ticker":
          return dir * a.ticker.localeCompare(b.ticker);
        case "asset_class":
          return dir * a.asset_class.localeCompare(b.asset_class);
        case "quantity":
          return dir * (a.quantity - b.quantity);
        case "avg_price":
          return dir * (a.avg_price - b.avg_price);
        case "current_price":
          return dir * (priceA - priceB);
        case "pnl": {
          const pa = a.avg_price > 0 ? (priceA - a.avg_price) / a.avg_price : 0;
          const pb = b.avg_price > 0 ? (priceB - b.avg_price) / b.avg_price : 0;
          return dir * (pa - pb);
        }
        case "total_value":
          return dir * (a.quantity * priceA - b.quantity * priceB);
        default:
          return 0;
      }
    });
  }, [data?.assets, filter, sortField, sortDir]);

  const handleBuy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !formData.ticker ||
      !formData.quantity ||
      !formData.avg_price ||
      !formData.asset_class
    ) {
      setMessage({ type: "error", text: "Preencha todos os campos obrigatórios" });
      return;
    }
    setSubmitting(true);
    try {
      await createAsset(formData as AssetCreate);
      setMessage({ type: "success", text: `${formData.ticker} adicionado à carteira` });
      setFormData({ asset_class: "stocks" });
      setShowBuyForm(false);
      await refresh();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao registrar",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSell = async () => {
    if (!sellTarget) return;
    setSubmitting(true);
    try {
      const result = await sellAsset(sellTarget.id);
      setLastSale(result);
      setMessage({
        type: "success",
        text: `${result.ticker} vendido por ${formatBRL(result.sale_value)}`,
      });
      setSellTarget(null);
      await refresh();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao vender",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const value = parseFloat(editPrice);
    if (Number.isNaN(value) || value <= 0) {
      setMessage({ type: "error", text: "Preço inválido" });
      return;
    }
    setSubmitting(true);
    try {
      await updateAsset(editing.id, { current_price: value });
      setMessage({ type: "success", text: `${editing.ticker} atualizado` });
      setEditing(null);
      await refresh();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao atualizar",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (asset: Asset) => {
    if (!confirm(`Remover ${asset.ticker} da carteira?`)) return;
    try {
      await deleteAsset(asset.id);
      await refresh();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao remover",
      });
    }
  };

  return (
    <div className="space-y-10 max-w-6xl">
      <div className="flex items-end justify-between">
        <div>
          <h2
            className="text-5xl tracking-tight leading-[1.05]"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Carteira
          </h2>
          <p
            className="text-sm mt-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Os ativos abaixo viram &quot;Carteira atual&quot; nos prompts do comitê.
          </p>
        </div>
        <button
          onClick={() => setShowBuyForm((v) => !v)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold"
          style={{ background: "var(--accent)", color: "white" }}
        >
          {showBuyForm ? <ChevronUp size={14} /> : <Plus size={14} />}
          {showBuyForm ? "Fechar" : "Adicionar ativo"}
        </button>
      </div>

      <AnimatePresence>
        {message && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="p-3.5 rounded-md text-sm font-medium"
            style={{
              background:
                message.type === "success"
                  ? "var(--success-light)"
                  : "var(--danger-light)",
              color:
                message.type === "success" ? "var(--success)" : "var(--danger)",
            }}
          >
            {message.text}
          </motion.div>
        )}

        {lastSale && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="p-5 rounded-md flex items-center justify-between"
            style={{ background: "var(--bg-card)", border: "1px solid var(--accent)" }}
          >
            <div className="flex items-center gap-3">
              <DollarSign size={18} style={{ color: "var(--accent)" }} />
              <div>
                <p
                  className="text-sm font-semibold"
                  style={{ color: "var(--text-primary)" }}
                >
                  {formatBRL(lastSale.sale_value)} liberados para redistribuir
                </p>
                <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                  Venda de {lastSale.ticker} · {formatNumber(lastSale.quantity)} un. a{" "}
                  {formatBRL(lastSale.price)}
                </p>
              </div>
            </div>
            <button
              onClick={() => setLastSale(null)}
              className="text-xs px-3 py-1.5 rounded-md font-medium"
              style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
            >
              Dispensar
            </button>
          </motion.div>
        )}

        {showBuyForm && (
          <motion.section
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div
              className="p-7 rounded-md"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <h3
                className="text-2xl tracking-tight mb-5"
                style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
              >
                Registrar ativo
              </h3>
              <form
                onSubmit={handleBuy}
                className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
              >
                <InputField
                  id="ticker"
                  label="Ticker"
                  value={formData.ticker ?? ""}
                  onChange={(v) =>
                    setFormData({ ...formData, ticker: v.toUpperCase() })
                  }
                  placeholder="PETR4"
                />
                <InputField
                  id="name"
                  label="Nome (opcional)"
                  value={formData.name ?? ""}
                  onChange={(v) => setFormData({ ...formData, name: v })}
                  placeholder="Petrobras PN"
                />
                <div>
                  <label
                    htmlFor="class"
                    className="block text-[11px] font-medium uppercase tracking-[0.16em] mb-2"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Classe
                  </label>
                  <select
                    id="class"
                    value={formData.asset_class}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        asset_class: e.target.value as AssetClass,
                      })
                    }
                    className="w-full px-4 py-2.5 rounded-md text-sm outline-none"
                    style={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border)",
                      color: "var(--text-primary)",
                    }}
                  >
                    {ASSET_CLASSES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>
                <InputField
                  id="qty"
                  label="Quantidade"
                  type="number"
                  value={formData.quantity?.toString() ?? ""}
                  onChange={(v) =>
                    setFormData({ ...formData, quantity: parseFloat(v) || 0 })
                  }
                  placeholder="100"
                />
                <InputField
                  id="avg"
                  label="Preço médio (R$)"
                  type="number"
                  value={formData.avg_price?.toString() ?? ""}
                  onChange={(v) =>
                    setFormData({ ...formData, avg_price: parseFloat(v) || 0 })
                  }
                  placeholder="38,50"
                />
                <InputField
                  id="current"
                  label="Preço atual (opcional)"
                  type="number"
                  value={formData.current_price?.toString() ?? ""}
                  onChange={(v) =>
                    setFormData({
                      ...formData,
                      current_price: v ? parseFloat(v) : undefined,
                    })
                  }
                  placeholder="42,10"
                />
                <InputField
                  id="date"
                  label="Data de entrada"
                  type="date"
                  value={formData.entry_date ?? ""}
                  onChange={(v) => setFormData({ ...formData, entry_date: v })}
                />
                <div className="sm:col-span-2 lg:col-span-3 flex gap-3 mt-2">
                  <button
                    type="submit"
                    disabled={submitting}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40"
                    style={{ background: "var(--success)", color: "white" }}
                  >
                    <Plus size={13} />
                    {submitting ? "Adicionando..." : "Adicionar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowBuyForm(false)}
                    className="px-5 py-2.5 rounded-md text-sm font-medium"
                    style={{
                      background: "var(--bg-secondary)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    Cancelar
                  </button>
                </div>
              </form>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <div className="flex gap-1">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className="px-4 py-1.5 rounded-md text-sm font-medium transition-colors"
            style={{
              background:
                filter === tab.value ? "var(--accent)" : "var(--bg-secondary)",
              color: filter === tab.value ? "white" : "var(--text-secondary)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        className="rounded-md overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {loading ? (
          <div className="p-8">
            <div
              className="animate-pulse h-48 rounded"
              style={{ background: "var(--bg-secondary)" }}
            />
          </div>
        ) : rows.length === 0 ? (
          <div className="text-center py-16">
            <PackageOpen
              size={36}
              className="mx-auto mb-4"
              style={{ color: "var(--border-strong)" }}
            />
            <p
              className="text-sm font-medium"
              style={{ color: "var(--text-secondary)" }}
            >
              Nenhum ativo encontrado
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Adicione ativos para a próxima rodada do comitê
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr
                  className="text-left text-[10px] uppercase tracking-[0.16em]"
                  style={{
                    color: "var(--text-muted)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  <SortHeader label="Ativo" field="ticker" current={sortField} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Classe" field="asset_class" current={sortField} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Qtd" field="quantity" current={sortField} dir={sortDir} onSort={handleSort} align="right" />
                  <SortHeader label="PM" field="avg_price" current={sortField} dir={sortDir} onSort={handleSort} align="right" />
                  <SortHeader label="Atual" field="current_price" current={sortField} dir={sortDir} onSort={handleSort} align="right" />
                  <SortHeader label="P&L" field="pnl" current={sortField} dir={sortDir} onSort={handleSort} align="right" />
                  <SortHeader label="Valor" field="total_value" current={sortField} dir={sortDir} onSort={handleSort} align="right" />
                  <th className="px-4 pb-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((asset) => {
                  const current = asset.current_price ?? asset.avg_price;
                  const total = asset.quantity * current;
                  const pnl =
                    asset.avg_price > 0
                      ? ((current - asset.avg_price) / asset.avg_price) * 100
                      : 0;

                  return (
                    <tr
                      key={asset.id}
                      className="group transition-colors"
                      style={{ borderBottom: "1px solid var(--border)" }}
                    >
                      <td className="px-4 py-3.5">
                        <span
                          className="font-semibold"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {asset.ticker}
                        </span>
                        {asset.name && (
                          <span
                            className="block text-xs mt-0.5"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {asset.name}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <span
                          className="text-xs px-2 py-0.5 rounded font-medium"
                          style={{
                            background: "var(--bg-secondary)",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {CLASS_LABELS[asset.asset_class]}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-right tabular">
                        {formatNumber(asset.quantity)}
                      </td>
                      <td className="px-4 py-3.5 text-right tabular">
                        {formatBRL(asset.avg_price)}
                      </td>
                      <td className="px-4 py-3.5 text-right tabular">
                        {formatBRL(current)}
                      </td>
                      <td
                        className="px-4 py-3.5 text-right tabular font-medium"
                        style={{
                          color:
                            pnl > 0
                              ? "var(--success)"
                              : pnl < 0
                                ? "var(--danger)"
                                : "var(--text-secondary)",
                        }}
                      >
                        {pnl > 0 ? "+" : ""}
                        {pnl.toFixed(2)}%
                      </td>
                      <td
                        className="px-4 py-3.5 text-right tabular font-semibold"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {formatBRL(total)}
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => setEditing(asset)}
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium"
                            style={{
                              background: "var(--bg-secondary)",
                              color: "var(--text-secondary)",
                            }}
                          >
                            <Pencil size={11} />
                            Preço
                          </button>
                          <button
                            onClick={() => setSellTarget(asset)}
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium"
                            style={{
                              background: "var(--danger-light)",
                              color: "var(--danger)",
                            }}
                          >
                            <Minus size={11} />
                            Vender
                          </button>
                          <button
                            onClick={() => handleDelete(asset)}
                            className="text-xs px-2.5 py-1.5 rounded-md font-medium"
                            style={{
                              background: "var(--bg-secondary)",
                              color: "var(--text-muted)",
                            }}
                          >
                            Remover
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <dialog
        ref={sellDialog}
        onClose={() => setSellTarget(null)}
        className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {sellTarget && (
          <>
            <h3
              className="text-2xl tracking-tight mb-2"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              Vender {sellTarget.ticker}?
            </h3>
            <div
              className="p-4 rounded-md mb-5 space-y-2"
              style={{ background: "var(--bg-secondary)" }}
            >
              <Row label="Quantidade" value={formatNumber(sellTarget.quantity)} />
              <Row
                label="Preço atual"
                value={formatBRL(sellTarget.current_price ?? sellTarget.avg_price)}
              />
              <div style={{ borderTop: "1px solid var(--border)" }} className="pt-2 mt-2">
                <Row
                  label="Valor total"
                  value={formatBRL(
                    sellTarget.quantity *
                      (sellTarget.current_price ?? sellTarget.avg_price)
                  )}
                  highlight
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleSell}
                disabled={submitting}
                className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40"
                style={{ background: "var(--danger)", color: "white" }}
              >
                <Minus size={13} />
                {submitting ? "Vendendo..." : "Confirmar venda"}
              </button>
              <button
                onClick={() => setSellTarget(null)}
                className="px-5 py-2.5 rounded-md text-sm font-medium"
                style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
              >
                Cancelar
              </button>
            </div>
          </>
        )}
      </dialog>

      <dialog
        ref={editDialog}
        onClose={() => setEditing(null)}
        className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        {editing && (
          <form onSubmit={handleUpdate}>
            <h3
              className="text-2xl tracking-tight mb-4"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              Atualizar preço · {editing.ticker}
            </h3>
            <InputField
              id="edit-price"
              label="Preço atual (R$)"
              type="number"
              value={editPrice}
              onChange={setEditPrice}
            />
            <div className="flex gap-3 mt-5">
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40"
                style={{ background: "var(--accent)", color: "white" }}
              >
                {submitting ? "Salvando..." : "Salvar preço"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="px-5 py-2.5 rounded-md text-sm font-medium"
                style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
              >
                Cancelar
              </button>
            </div>
          </form>
        )}
      </dialog>
    </div>
  );
};

const Row = ({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) => (
  <div className="flex justify-between">
    <span className="text-xs" style={{ color: "var(--text-muted)" }}>
      {label}
    </span>
    <span
      className={`tabular font-semibold ${highlight ? "text-lg" : "text-sm"}`}
      style={{ color: highlight ? "var(--accent)" : "var(--text-primary)" }}
    >
      {value}
    </span>
  </div>
);

const SortHeader = ({
  label,
  field,
  current,
  dir,
  onSort,
  align = "left",
}: {
  label: string;
  field: SortField;
  current: SortField;
  dir: SortDirection;
  onSort: (f: SortField) => void;
  align?: "left" | "right";
}) => {
  const isActive = field === current;
  return (
    <th
      className={`px-4 pb-3 font-medium ${align === "right" ? "text-right" : "text-left"}`}
    >
      <button
        onClick={() => onSort(field)}
        className={`inline-flex items-center gap-1 ${align === "right" ? "justify-end" : ""}`}
        style={{ color: isActive ? "var(--text-primary)" : undefined }}
      >
        {label}
        {isActive ? (
          dir === "asc" ? (
            <ChevronUp size={11} />
          ) : (
            <ChevronDown size={11} />
          )
        ) : (
          <ArrowUpDown size={9} className="opacity-40" />
        )}
      </button>
    </th>
  );
};

const InputField = ({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) => (
  <div>
    <label
      htmlFor={id}
      className="block text-[11px] font-medium uppercase tracking-[0.16em] mb-2"
      style={{ color: "var(--text-muted)" }}
    >
      {label}
    </label>
    <input
      id={id}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      step={type === "number" ? "any" : undefined}
      className="w-full px-4 py-2.5 rounded-md text-sm outline-none"
      style={{
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
      }}
    />
  </div>
);

export default AtivosPage;
