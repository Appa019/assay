"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check,
  ClipboardList,
  SkipForward,
  Target,
  X,
} from "lucide-react";
import {
  executeOrder,
  skipOrder,
  type AssetClass,
  type Order,
} from "@/lib/api";
import { formatBRL, formatDateTime, formatNumber } from "@/lib/format";

const CLASS_LABELS: Record<AssetClass, string> = {
  fixed_income: "RF",
  stocks: "Ações",
  crypto: "Crypto",
};

const STATUS_RANK: Record<Order["status"], number> = {
  pending: 0,
  executed: 1,
  skipped: 2,
};

/**
 * Committee order sheet: pending orders with "Executei"/"Pular" actions,
 * executed ones showing real fill vs plan, skipped ones de-emphasized.
 */
export const OrdersPanel = ({
  orders,
  title = "Folha de ordens",
  subtitle,
  onChanged,
}: {
  orders: Order[];
  title?: string;
  subtitle?: string;
  onChanged: () => Promise<void>;
}) => {
  const [executing, setExecuting] = useState<Order | null>(null);
  const [skipping, setSkipping] = useState<Order | null>(null);
  const [message, setMessage] = useState<
    { type: "success" | "error"; text: string } | null
  >(null);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 6000);
    return () => clearTimeout(t);
  }, [message]);

  const sorted = useMemo(
    () =>
      [...orders].sort(
        (a, b) =>
          STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
          b.amount_brl - a.amount_brl
      ),
    [orders]
  );

  const pendingCount = orders.filter((o) => o.status === "pending").length;

  return (
    <section className="space-y-4">
      <div>
        <h3
          className="text-2xl tracking-tight flex items-center gap-2.5"
          style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
        >
          <ClipboardList size={18} style={{ color: "var(--text-muted)" }} />
          {title}
          {pendingCount > 0 && (
            <span
              className="text-[11px] font-semibold px-2 py-0.5 rounded-full tabular"
              style={{ background: "var(--accent-light)", color: "var(--accent-strong)" }}
            >
              {pendingCount} pendente{pendingCount > 1 ? "s" : ""}
            </span>
          )}
        </h3>
        {subtitle && (
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
            {subtitle}
          </p>
        )}
      </div>

      <AnimatePresence>
        {message && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="p-3 rounded-md text-sm font-medium"
            style={{
              background:
                message.type === "success"
                  ? "var(--success-light)"
                  : "var(--danger-light)",
              color: message.type === "success" ? "var(--success)" : "var(--danger)",
            }}
          >
            {message.text}
          </motion.p>
        )}
      </AnimatePresence>

      <div className="space-y-2.5">
        {sorted.map((order) => (
          <OrderCard
            key={order.id}
            order={order}
            onExecute={() => setExecuting(order)}
            onSkip={() => setSkipping(order)}
          />
        ))}
      </div>

      <ExecuteDialog
        order={executing}
        onClose={() => setExecuting(null)}
        onDone={async (text) => {
          setMessage({ type: "success", text });
          setExecuting(null);
          await onChanged();
        }}
      />
      <SkipDialog
        order={skipping}
        onClose={() => setSkipping(null)}
        onDone={async (text) => {
          setMessage({ type: "success", text });
          setSkipping(null);
          await onChanged();
        }}
      />
    </section>
  );
};

const OrderCard = ({
  order,
  onExecute,
  onSkip,
}: {
  order: Order;
  onExecute: () => void;
  onSkip: () => void;
}) => {
  const pending = order.status === "pending";
  const executed = order.status === "executed";
  const executedTotal =
    order.executed_quantity !== null && order.executed_price !== null
      ? order.executed_quantity * order.executed_price
      : null;

  return (
    <article
      className="rounded-md px-5 py-4"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${executed ? "var(--success)" : "var(--border)"}`,
        opacity: order.status === "skipped" ? 0.55 : 1,
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span
              className="font-semibold text-base"
              style={{ color: "var(--text-primary)" }}
            >
              {order.ticker}
            </span>
            <span
              className="text-[11px] px-1.5 py-0.5 rounded font-medium"
              style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
            >
              {CLASS_LABELS[order.asset_class]}
            </span>
            <span
              className="tabular font-semibold text-sm"
              style={{ color: "var(--text-primary)" }}
            >
              {formatBRL(order.amount_brl)}
            </span>
            {order.pct_of_contribution !== null && (
              <span className="text-xs tabular" style={{ color: "var(--text-muted)" }}>
                {order.pct_of_contribution.toFixed(1)}% do aporte
              </span>
            )}
            <StatusChip status={order.status} />
          </div>

          {(order.target_price !== null || order.stop_price !== null) && (
            <p
              className="flex items-center gap-1.5 text-[11px] mt-1.5 tabular"
              style={{ color: "var(--text-muted)" }}
            >
              <Target size={11} />
              {order.target_price !== null && (
                <>
                  alvo{" "}
                  <span style={{ color: "var(--success)" }}>
                    {formatBRL(order.target_price)}
                  </span>
                </>
              )}
              {order.target_price !== null && order.stop_price !== null && <span>·</span>}
              {order.stop_price !== null && (
                <>
                  stop{" "}
                  <span style={{ color: "var(--danger)" }}>
                    {formatBRL(order.stop_price)}
                  </span>
                </>
              )}
            </p>
          )}

          {order.thesis && (
            <p
              className="text-xs mt-1.5 leading-relaxed max-w-3xl"
              style={{ color: "var(--text-secondary)" }}
            >
              {order.thesis}
            </p>
          )}

          {executed && executedTotal !== null && (
            <p className="text-xs mt-2 tabular" style={{ color: "var(--text-secondary)" }}>
              Executada: {formatNumber(order.executed_quantity)} un. a{" "}
              {formatBRL(order.executed_price)} = {formatBRL(executedTotal)}{" "}
              <span style={{ color: "var(--text-muted)" }}>
                (planejado {formatBRL(order.amount_brl)} ·{" "}
                {executedTotal >= order.amount_brl ? "+" : ""}
                {formatBRL(executedTotal - order.amount_brl)})
                {order.executed_at ? ` · ${formatDateTime(order.executed_at)}` : ""}
              </span>
            </p>
          )}
        </div>

        {pending && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onExecute}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-md text-xs font-semibold"
              style={{ background: "var(--success)", color: "white" }}
            >
              <Check size={12} />
              Executei
            </button>
            <button
              onClick={onSkip}
              className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium"
              style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
            >
              <SkipForward size={12} />
              Pular
            </button>
          </div>
        )}
      </div>
    </article>
  );
};

const StatusChip = ({ status }: { status: Order["status"] }) => {
  if (status === "pending") return null;
  const executed = status === "executed";
  return (
    <span
      className="text-[10px] font-semibold uppercase tracking-[0.12em] px-2 py-0.5 rounded-full"
      style={{
        background: executed ? "var(--success-light)" : "var(--bg-secondary)",
        color: executed ? "var(--success)" : "var(--text-muted)",
      }}
    >
      {executed ? "Executada" : "Pulada"}
    </span>
  );
};

const ExecuteDialog = ({
  order,
  onClose,
  onDone,
}: {
  order: Order | null;
  onClose: () => void;
  onDone: (message: string) => Promise<void>;
}) => {
  const ref = useRef<HTMLDialogElement>(null);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (order) {
      setQuantity("");
      setPrice(
        order.target_price !== null ? String(order.target_price) : ""
      );
      setError(null);
      ref.current?.showModal();
    } else {
      ref.current?.close();
    }
  }, [order]);

  const qty = parseFloat(quantity);
  const prc = parseFloat(price);
  const total = !Number.isNaN(qty) && !Number.isNaN(prc) ? qty * prc : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!order) return;
    if (Number.isNaN(qty) || qty <= 0 || Number.isNaN(prc) || prc <= 0) {
      setError("Informe quantidade e preço válidos");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await executeOrder(order.id, qty, prc);
      await onDone(`${order.ticker}: execução registrada (${formatBRL(qty * prc)})`);
    } catch (err) {
      // 409 detail: already executed/skipped — show the backend message.
      setError(err instanceof Error ? err.message : "Erro ao registrar execução");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {order && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex items-start justify-between">
            <h3
              className="text-2xl tracking-tight"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              Executei {order.ticker}
            </h3>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-md"
              style={{ color: "var(--text-muted)" }}
            >
              <X size={16} />
            </button>
          </div>
          <p className="text-xs -mt-2" style={{ color: "var(--text-muted)" }}>
            Planejado: {formatBRL(order.amount_brl)}
            {order.target_price !== null
              ? ` · alvo ${formatBRL(order.target_price)}`
              : ""}
          </p>

          <Field
            id="exec-qty"
            label="Quantidade executada"
            value={quantity}
            onChange={setQuantity}
            placeholder="100"
            autoFocus
          />
          <Field
            id="exec-price"
            label="Preço pago (R$)"
            value={price}
            onChange={setPrice}
            placeholder="38,50"
          />

          {total !== null && (
            <p className="text-sm tabular" style={{ color: "var(--text-secondary)" }}>
              Total: <strong style={{ color: "var(--text-primary)" }}>{formatBRL(total)}</strong>{" "}
              <span style={{ color: "var(--text-muted)" }}>
                ({total >= order.amount_brl ? "+" : ""}
                {formatBRL(total - order.amount_brl)} vs planejado)
              </span>
            </p>
          )}

          {error && (
            <p className="text-sm font-medium" style={{ color: "var(--danger)" }}>
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40"
              style={{ background: "var(--success)", color: "white" }}
            >
              <Check size={13} />
              {submitting ? "Registrando..." : "Confirmar execução"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-md text-sm font-medium"
              style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
            >
              Cancelar
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
};

const SkipDialog = ({
  order,
  onClose,
  onDone,
}: {
  order: Order | null;
  onClose: () => void;
  onDone: (message: string) => Promise<void>;
}) => {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (order) {
      setReason("");
      setError(null);
      ref.current?.showModal();
    } else {
      ref.current?.close();
    }
  }, [order]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!order) return;
    setSubmitting(true);
    setError(null);
    try {
      await skipOrder(order.id, reason.trim() || undefined);
      await onDone(`${order.ticker}: ordem pulada`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao pular ordem");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="p-7 rounded-md max-w-md w-full backdrop:bg-black/40"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {order && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <h3
            className="text-2xl tracking-tight"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Pular {order.ticker}?
          </h3>
          <p className="text-xs -mt-2" style={{ color: "var(--text-muted)" }}>
            A ordem fica registrada como não executada — sem efeito na carteira.
          </p>
          <div>
            <label
              htmlFor="skip-reason"
              className="block text-[11px] font-medium uppercase tracking-[0.16em] mb-2"
              style={{ color: "var(--text-muted)" }}
            >
              Motivo (opcional)
            </label>
            <input
              id="skip-reason"
              value={reason}
              maxLength={200}
              onChange={(e) => setReason(e.target.value)}
              placeholder="ex: preço fugiu do alvo"
              className="w-full px-4 py-2.5 rounded-md text-sm outline-none"
              style={{
                background: "var(--bg-secondary)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          {error && (
            <p className="text-sm font-medium" style={{ color: "var(--danger)" }}>
              {error}
            </p>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40"
              style={{ background: "var(--accent)", color: "white" }}
            >
              <SkipForward size={13} />
              {submitting ? "Registrando..." : "Pular ordem"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-md text-sm font-medium"
              style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
            >
              Cancelar
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
};

const Field = ({
  id,
  label,
  value,
  onChange,
  placeholder,
  autoFocus,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
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
      type="number"
      step="any"
      min="0"
      autoFocus={autoFocus}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-4 py-2.5 rounded-md text-sm outline-none tabular"
      style={{
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
      }}
    />
  </div>
);
