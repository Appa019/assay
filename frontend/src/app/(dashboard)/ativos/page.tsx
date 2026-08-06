"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowUpDown,
  ChevronDown,
  ChevronUp,
  DollarSign,
  History,
  Lock,
  LockOpen,
  Minus,
  PackageOpen,
  Pencil,
  Plus,
  RefreshCw,
} from "lucide-react";
import {
  createAsset,
  deleteAsset,
  fetchTrades,
  refreshPortfolioPrices,
  sellAsset,
  updateAsset,
  type Asset,
  type AssetClass,
  type AssetCreate,
  type SaleResult,
  type Trade,
} from "@/lib/api";
import { usePortfolio } from "@/hooks/use-portfolio";
import {
  daysSince,
  formatBRL,
  formatDate,
  formatDateTime,
  formatNumber,
  parseLocalDate,
} from "@/lib/format";

const MIN_HOLDING_DAYS = 30;

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

type LockInfo =
  | { kind: "daily_liquidity" }
  | { kind: "locked"; remainingDays: number; unlockDate: Date }
  | { kind: "unlocked" };

/** 30-day sell lock per LOT — stocks/crypto only; CDB has daily liquidity. */
const lockInfoFor = (asset: Asset): LockInfo => {
  if (asset.asset_class === "fixed_income") return { kind: "daily_liquidity" };
  const held = daysSince(asset.entry_date);
  if (held >= MIN_HOLDING_DAYS) return { kind: "unlocked" };
  const unlockDate = parseLocalDate(asset.entry_date);
  unlockDate.setDate(unlockDate.getDate() + MIN_HOLDING_DAYS);
  return { kind: "locked", remainingDays: MIN_HOLDING_DAYS - held, unlockDate };
};

type SortField =
  | "ticker"
  | "asset_class"
  | "quantity"
  | "avg_price"
  | "current_price"
  | "pnl"
  | "total_value"
  | "lock";

type SortDirection = "asc" | "desc";

/** Phone-only sort picker — same fields the desktop table header exposes. */
const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "total_value", label: "Valor" },
  { value: "ticker", label: "Ativo" },
  { value: "asset_class", label: "Classe" },
  { value: "lock", label: "Trava" },
  { value: "quantity", label: "Quantidade" },
  { value: "avg_price", label: "Preço médio" },
  { value: "current_price", label: "Preço atual" },
  { value: "pnl", label: "P&L" },
];

const realizedPnlColor = (trade: Trade): string =>
  trade.realized_pnl_brl === null
    ? "var(--text-muted)"
    : trade.realized_pnl_brl >= 0
      ? "var(--success)"
      : "var(--danger)";

const realizedPnlLabel = (trade: Trade): string =>
  trade.realized_pnl_brl === null
    ? "—"
    : `${trade.realized_pnl_brl >= 0 ? "+" : ""}${formatBRL(trade.realized_pnl_brl)}${
        trade.realized_pnl_pct !== null
          ? ` (${trade.realized_pnl_pct >= 0 ? "+" : ""}${trade.realized_pnl_pct.toFixed(2)}%)`
          : ""
      }`;

/**
 * Portfolio section. Exported by name so /investimentos can host it as a
 * sub-tab; the default export keeps this route alive for existing deep links.
 */
export const AtivosView = () => {
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
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);
  const [filter, setFilter] = useState<string>("all");
  const [sortField, setSortField] = useState<SortField>("total_value");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const sellDialog = useRef<HTMLDialogElement>(null);
  const editDialog = useRef<HTMLDialogElement>(null);

  const loadTrades = useCallback(async () => {
    try {
      setTrades(await fetchTrades());
    } catch {
      // Network error: keep whatever was on screen, section hides when null.
    }
  }, []);

  useEffect(() => {
    void loadTrades();
  }, [loadTrades]);

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
    const t = setTimeout(() => setMessage(null), 6000);
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
        case "lock":
          return dir * (daysSince(a.entry_date) - daysSince(b.entry_date));
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
      // Explicit shape instead of a cast: a new required field on AssetCreate
      // must fail HERE at compile time, not as a silent 422 at runtime.
      const payload: AssetCreate = {
        ticker: formData.ticker,
        name: formData.name,
        asset_class: formData.asset_class,
        quantity: formData.quantity,
        avg_price: formData.avg_price,
        current_price: formData.current_price,
        entry_date: formData.entry_date,
      };
      await createAsset(payload);
      setMessage({ type: "success", text: `${formData.ticker} adicionado à carteira` });
      setFormData({ asset_class: "stocks" });
      setShowBuyForm(false);
      await Promise.all([refresh(), loadTrades()]);
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
      await Promise.all([refresh(), loadTrades()]);
    } catch (err) {
      // A 409 carries the pt-BR lock message from the backend — show it as-is.
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao vender",
      });
    } finally {
      setSellTarget(null);
      setSubmitting(false);
    }
  };

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    try {
      const result = await refreshPortfolioPrices();
      const warningSuffix =
        result.warnings.length > 0 ? ` · avisos: ${result.warnings.join(" · ")}` : "";
      setMessage({
        type: result.warnings.length > 0 ? "error" : "success",
        text: `${result.updated} preço(s) atualizado(s)${warningSuffix}`,
      });
      await refresh();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Erro ao atualizar preços",
      });
    } finally {
      setRefreshing(false);
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

  const sellLock = sellTarget ? lockInfoFor(sellTarget) : null;

  return (
    <div className="space-y-8 md:space-y-10 max-w-6xl">
      <div className="flex flex-col max-md:gap-5 md:flex-row md:items-end md:justify-between">
        <div>
          <h2
            className="text-4xl md:text-5xl tracking-tight leading-[1.05]"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Carteira
          </h2>
          <p
            className="text-sm mt-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Cada compra é um lote com trava própria de {MIN_HOLDING_DAYS} dias
            (ações e crypto). Os ativos abaixo viram &quot;Carteira atual&quot; nos
            prompts do comitê.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => void handleRefreshPrices()}
            disabled={refreshing || loading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-md text-sm font-medium disabled:opacity-40 max-md:min-h-11 max-md:flex-1 max-md:justify-center"
            style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
            {refreshing ? "Atualizando..." : "Atualizar preços"}
          </button>
          <button
            onClick={() => setShowBuyForm((v) => !v)}
            className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold max-md:min-h-11 max-md:flex-1 max-md:justify-center"
            style={{ background: "var(--accent)", color: "white" }}
          >
            {showBuyForm ? <ChevronUp size={14} /> : <Plus size={14} />}
            {showBuyForm ? "Fechar" : "Adicionar ativo"}
          </button>
        </div>
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
            className="p-5 rounded-md flex items-center justify-between max-md:flex-col max-md:items-start max-md:gap-4"
            style={{ background: "var(--bg-card)", border: "1px solid var(--accent)" }}
          >
            <div className="flex items-center gap-3 min-w-0">
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
              className="text-xs px-3 py-1.5 rounded-md font-medium max-md:min-h-11 max-md:px-4"
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
              className="p-7 rounded-md max-md:p-5"
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
                    className="w-full px-4 py-2.5 rounded-md text-sm outline-none max-md:text-base max-md:min-h-11"
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
                    className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40 max-md:min-h-11 max-md:flex-1 max-md:justify-center"
                    style={{ background: "var(--success)", color: "white" }}
                  >
                    <Plus size={13} />
                    {submitting ? "Adicionando..." : "Adicionar"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowBuyForm(false)}
                    className="px-5 py-2.5 rounded-md text-sm font-medium max-md:min-h-11 max-md:flex-1"
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

      <div className="flex gap-1 max-md:flex-wrap max-md:gap-1.5">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className="px-4 py-1.5 rounded-md text-sm font-medium transition-colors max-md:min-h-11"
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
              Registre aqui o que comprar da folha de ordens do comitê
            </p>
          </div>
        ) : (
          <>
            {/* Phone: the sortable header row is gone, so sorting moves into a
                dedicated control that reuses the very same handler. */}
            <div
              className="flex items-center gap-2 px-4 py-3 md:hidden"
              style={{ borderBottom: "1px solid var(--border)" }}
            >
              <label
                htmlFor="sort-field"
                className="text-[10px] uppercase tracking-[0.16em] shrink-0"
                style={{ color: "var(--text-muted)" }}
              >
                Ordenar
              </label>
              <select
                id="sort-field"
                value={sortField}
                onChange={(e) => handleSort(e.target.value as SortField)}
                className="flex-1 min-w-0 min-h-11 px-3 rounded-md text-base outline-none"
                style={{
                  background: "var(--bg-secondary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              >
                {SORT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => handleSort(sortField)}
                aria-label={
                  sortDir === "asc"
                    ? "Ordenar do maior para o menor"
                    : "Ordenar do menor para o maior"
                }
                className="grid h-11 w-11 shrink-0 place-items-center rounded-md"
                style={{
                  background: "var(--bg-secondary)",
                  color: "var(--text-secondary)",
                }}
              >
                {sortDir === "asc" ? (
                  <ChevronUp size={16} />
                ) : (
                  <ChevronDown size={16} />
                )}
              </button>
            </div>

            <ul className="md:hidden">
              {rows.map((asset) => {
                const current = asset.current_price ?? asset.avg_price;
                const total = asset.quantity * current;
                const pnl =
                  asset.avg_price > 0
                    ? ((current - asset.avg_price) / asset.avg_price) * 100
                    : 0;
                const lock = lockInfoFor(asset);
                const locked = lock.kind === "locked";
                const pnlColor =
                  pnl > 0
                    ? "var(--success)"
                    : pnl < 0
                      ? "var(--danger)"
                      : "var(--text-secondary)";

                return (
                  <li
                    key={asset.id}
                    className="px-4 py-4"
                    style={{ borderBottom: "1px solid var(--border)" }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p
                          className="text-[15px] font-semibold truncate"
                          style={{ color: "var(--text-primary)" }}
                          title={asset.thesis ?? undefined}
                        >
                          {asset.ticker}
                        </p>
                        {asset.name && (
                          <p
                            className="text-xs mt-0.5 truncate"
                            style={{ color: "var(--text-muted)" }}
                          >
                            {asset.name}
                          </p>
                        )}
                      </div>
                      <p
                        className="tabular text-[15px] font-semibold shrink-0"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {formatBRL(total)}
                      </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
                      <span
                        className="text-xs px-2 py-0.5 rounded font-medium"
                        style={{
                          background: "var(--bg-secondary)",
                          color: "var(--text-secondary)",
                        }}
                      >
                        {CLASS_LABELS[asset.asset_class]}
                      </span>
                      <LockBadge lock={lock} entryDate={asset.entry_date} />
                    </div>

                    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 mt-3.5">
                      <CardStat label="Qtd" value={formatNumber(asset.quantity)} />
                      <CardStat label="PM" value={formatBRL(asset.avg_price)} />
                      <CardStat label="Atual" value={formatBRL(current)} />
                      <CardStat
                        label="P&L"
                        value={`${pnl > 0 ? "+" : ""}${pnl.toFixed(2)}%`}
                        color={pnlColor}
                      />
                    </dl>

                    <TargetStopLine asset={asset} className="text-[11px] mt-3" />

                    <div className="flex gap-2 mt-4">
                      <button
                        onClick={() => setEditing(asset)}
                        className="flex flex-1 min-h-11 items-center justify-center gap-1.5 rounded-md text-xs font-medium"
                        style={{
                          background: "var(--bg-secondary)",
                          color: "var(--text-secondary)",
                        }}
                      >
                        <Pencil size={12} />
                        Preço
                      </button>
                      <button
                        onClick={() => setSellTarget(asset)}
                        disabled={locked}
                        className="flex flex-1 min-h-11 items-center justify-center gap-1.5 rounded-md text-xs font-medium disabled:opacity-45"
                        style={{
                          background: "var(--danger-light)",
                          color: "var(--danger)",
                        }}
                      >
                        {locked ? <Lock size={12} /> : <Minus size={12} />}
                        Vender
                      </button>
                      <button
                        onClick={() => handleDelete(asset)}
                        className="flex flex-1 min-h-11 items-center justify-center rounded-md text-xs font-medium"
                        style={{
                          background: "var(--bg-secondary)",
                          color: "var(--text-muted)",
                        }}
                      >
                        Remover
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>

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
                    <SortHeader label="Ativo" field="ticker" current={sortField} dir={sortDir} onSort={handleSort} />
                    <SortHeader label="Classe" field="asset_class" current={sortField} dir={sortDir} onSort={handleSort} />
                    <SortHeader label="Trava" field="lock" current={sortField} dir={sortDir} onSort={handleSort} />
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
                    const lock = lockInfoFor(asset);
                    const locked = lock.kind === "locked";

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
                            title={asset.thesis ?? undefined}
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
                          <TargetStopLine asset={asset} className="text-[11px] mt-0.5" />
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
                        <td className="px-4 py-3.5">
                          <LockBadge lock={lock} entryDate={asset.entry_date} />
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
                              disabled={locked}
                              title={
                                lock.kind === "locked"
                                  ? `Trava de ${MIN_HOLDING_DAYS} dias por lote — libera em ${lock.remainingDays}d (${lock.unlockDate.toLocaleDateString("pt-BR")})`
                                  : undefined
                              }
                              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium disabled:opacity-45"
                              style={{
                                background: "var(--danger-light)",
                                color: "var(--danger)",
                              }}
                            >
                              {locked ? <Lock size={11} /> : <Minus size={11} />}
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
          </>
        )}
      </div>

      {trades !== null && <TradesSection trades={trades} />}

      <dialog
        ref={sellDialog}
        onClose={() => setSellTarget(null)}
        className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40 max-md:p-5 max-md:max-h-[85dvh] max-md:overflow-y-auto"
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
            {sellLock?.kind === "locked" && (
              <p
                className="p-3 rounded-md text-xs mb-4 flex items-start gap-2"
                style={{ background: "var(--warning-light)", color: "var(--text-secondary)" }}
              >
                <Lock size={13} className="mt-0.5 shrink-0" style={{ color: "var(--warning)" }} />
                Lote travado: faltam {sellLock.remainingDays} dia(s) — o backend
                vai recusar a venda antes de{" "}
                {sellLock.unlockDate.toLocaleDateString("pt-BR")}.
              </p>
            )}
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
            <div className="flex gap-3 max-md:flex-col">
              <button
                onClick={handleSell}
                disabled={submitting}
                className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40 max-md:min-h-11 max-md:w-full max-md:justify-center"
                style={{ background: "var(--danger)", color: "white" }}
              >
                <Minus size={13} />
                {submitting ? "Vendendo..." : "Confirmar venda"}
              </button>
              <button
                onClick={() => setSellTarget(null)}
                className="px-5 py-2.5 rounded-md text-sm font-medium max-md:min-h-11 max-md:w-full"
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
        className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40 max-md:p-5 max-md:max-h-[85dvh] max-md:overflow-y-auto"
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
            <div className="flex gap-3 mt-5 max-md:flex-col">
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40 max-md:min-h-11 max-md:w-full"
                style={{ background: "var(--accent)", color: "white" }}
              >
                {submitting ? "Salvando..." : "Salvar preço"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="px-5 py-2.5 rounded-md text-sm font-medium max-md:min-h-11 max-md:w-full"
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

/** Label-over-value pair used by the phone card lists that replace the tables. */
const CardStat = ({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) => (
  <div className="min-w-0">
    <dt
      className="text-[10px] uppercase tracking-[0.14em]"
      style={{ color: "var(--text-muted)" }}
    >
      {label}
    </dt>
    <dd
      className="tabular text-sm font-medium mt-0.5 truncate"
      style={{ color: color ?? "var(--text-primary)" }}
    >
      {value}
    </dd>
  </div>
);

const TargetStopLine = ({
  asset,
  className,
}: {
  asset: Asset;
  className: string;
}) => {
  if (asset.target_price === null && asset.stop_price === null) return null;
  return (
    <span
      className={`block tabular ${className}`}
      style={{ color: "var(--text-muted)" }}
    >
      {asset.target_price !== null && (
        <>
          alvo{" "}
          <span style={{ color: "var(--success)" }}>
            {formatBRL(asset.target_price)}
          </span>
        </>
      )}
      {asset.target_price !== null && asset.stop_price !== null && " · "}
      {asset.stop_price !== null && (
        <>
          stop{" "}
          <span style={{ color: "var(--danger)" }}>
            {formatBRL(asset.stop_price)}
          </span>
        </>
      )}
    </span>
  );
};

const LockBadge = ({ lock, entryDate }: { lock: LockInfo; entryDate: string }) => {
  if (lock.kind === "daily_liquidity") {
    return (
      <span
        className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded"
        style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
        title="CDB: sem trava, vendável a qualquer momento"
      >
        Liquidez diária
      </span>
    );
  }
  if (lock.kind === "locked") {
    return (
      <span
        className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded"
        style={{ background: "var(--warning-light)", color: "var(--text-secondary)" }}
        title={`Lote de ${formatDate(entryDate)} · libera em ${lock.unlockDate.toLocaleDateString("pt-BR")}`}
      >
        <Lock size={10} style={{ color: "var(--warning)" }} />
        faltam {lock.remainingDays}d
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded"
      style={{ background: "var(--success-light)", color: "var(--success)" }}
      title={`Lote de ${formatDate(entryDate)} · trava cumprida`}
    >
      <LockOpen size={10} />
      liberado
    </span>
  );
};

const TradesSection = ({ trades }: { trades: Trade[] }) => (
  <section className="space-y-4">
    <div>
      <h3
        className="text-2xl tracking-tight flex items-center gap-2.5"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        <History size={18} style={{ color: "var(--text-muted)" }} />
        Histórico de operações
      </h3>
      <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
        Compras e vendas registradas, com P&amp;L realizado nas vendas
      </p>
    </div>
    {trades.length === 0 ? (
      <div
        className="p-6 text-sm rounded-md"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          color: "var(--text-muted)",
        }}
      >
        Nenhuma operação registrada ainda
      </div>
    ) : (
      <div
        className="rounded-md overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <ul className="md:hidden">
          {trades.map((trade) => {
            const isBuy = trade.side === "buy";
            return (
              <li
                key={trade.id}
                className="px-4 py-3.5"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="font-semibold truncate"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {trade.ticker}
                      </span>
                      <span
                        className="text-[11px] px-1.5 py-0.5 rounded shrink-0"
                        style={{
                          background: "var(--bg-secondary)",
                          color: "var(--text-muted)",
                        }}
                      >
                        {CLASS_LABELS[trade.asset_class]}
                      </span>
                    </div>
                    <p
                      className="tabular text-[11px] mt-1"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {formatDateTime(trade.executed_at)}
                    </p>
                  </div>
                  <span
                    className="text-[11px] font-semibold px-2 py-0.5 rounded shrink-0"
                    style={{
                      background: isBuy ? "var(--success-light)" : "var(--danger-light)",
                      color: isBuy ? "var(--success)" : "var(--danger)",
                    }}
                  >
                    {isBuy ? "Compra" : "Venda"}
                  </span>
                </div>

                <dl className="grid grid-cols-3 gap-x-3 gap-y-2 mt-3">
                  <CardStat label="Qtd" value={formatNumber(trade.quantity)} />
                  <CardStat label="Preço" value={formatBRL(trade.price)} />
                  <CardStat label="Total" value={formatBRL(trade.total_brl)} />
                </dl>

                {trade.realized_pnl_brl !== null && (
                  <div
                    className="flex items-baseline justify-between gap-3 mt-3 pt-3"
                    style={{ borderTop: "1px solid var(--border)" }}
                  >
                    <span
                      className="text-[10px] uppercase tracking-[0.14em]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      P&amp;L realizado
                    </span>
                    <span
                      className="tabular text-sm font-medium text-right"
                      style={{ color: realizedPnlColor(trade) }}
                    >
                      {realizedPnlLabel(trade)}
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>

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
                <th className="px-4 py-3 font-medium">Data</th>
                <th className="px-4 py-3 font-medium">Ativo</th>
                <th className="px-4 py-3 font-medium">Lado</th>
                <th className="px-4 py-3 font-medium text-right">Qtd</th>
                <th className="px-4 py-3 font-medium text-right">Preço</th>
                <th className="px-4 py-3 font-medium text-right">Total</th>
                <th className="px-4 py-3 font-medium text-right">P&amp;L realizado</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const isBuy = trade.side === "buy";
                const pnlColor = realizedPnlColor(trade);
                return (
                  <tr
                    key={trade.id}
                    style={{ borderBottom: "1px solid var(--border)" }}
                  >
                    <td className="px-4 py-3 tabular text-xs" style={{ color: "var(--text-secondary)" }}>
                      {formatDateTime(trade.executed_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-semibold" style={{ color: "var(--text-primary)" }}>
                        {trade.ticker}
                      </span>
                      <span
                        className="ml-2 text-[11px] px-1.5 py-0.5 rounded"
                        style={{ background: "var(--bg-secondary)", color: "var(--text-muted)" }}
                      >
                        {CLASS_LABELS[trade.asset_class]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="text-[11px] font-semibold px-2 py-0.5 rounded"
                        style={{
                          background: isBuy ? "var(--success-light)" : "var(--danger-light)",
                          color: isBuy ? "var(--success)" : "var(--danger)",
                        }}
                      >
                        {isBuy ? "Compra" : "Venda"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tabular">
                      {formatNumber(trade.quantity)}
                    </td>
                    <td className="px-4 py-3 text-right tabular">
                      {formatBRL(trade.price)}
                    </td>
                    <td className="px-4 py-3 text-right tabular font-semibold" style={{ color: "var(--text-primary)" }}>
                      {formatBRL(trade.total_brl)}
                    </td>
                    <td className="px-4 py-3 text-right tabular font-medium" style={{ color: pnlColor }}>
                      {realizedPnlLabel(trade)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    )}
  </section>
);

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
      /* text-base below md: anything under 16px makes iOS zoom on focus. */
      className="w-full px-4 py-2.5 rounded-md text-sm outline-none max-md:text-base max-md:min-h-11"
      style={{
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
      }}
    />
  </div>
);

export default AtivosView;
