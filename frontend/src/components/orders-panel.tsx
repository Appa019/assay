"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check,
  ClipboardList,
  Copy,
  SkipForward,
  Target,
  X,
} from "lucide-react";
import {
  executeOrder,
  skipOrder,
  type AssetClass,
  type Order,
  type TicketLine,
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
          className="text-2xl tracking-tight flex flex-wrap items-center gap-2.5"
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
            className="p-3 rounded-md text-sm font-medium break-words"
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
      className="rounded-md px-4 py-4 md:px-5"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${executed ? "var(--success)" : "var(--border)"}`,
        opacity: order.status === "skipped" ? 0.55 : 1,
      }}
    >
      {/* Below md the card stacks: identity line, figures line, actions row. */}
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span
              className="font-semibold text-base truncate"
              style={{ color: "var(--text-primary)" }}
            >
              {order.ticker}
            </span>
            <span
              className="text-[11px] px-1.5 py-0.5 rounded font-medium shrink-0"
              style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
            >
              {CLASS_LABELS[order.asset_class]}
            </span>
            {/* w-full drops the figures to their own line on phones; at md they
                rejoin the identity row with the exact same gap. */}
            <span className="flex w-full items-center gap-2.5 flex-wrap md:w-auto">
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
            </span>
          </div>

          {pending && <Ticket lines={order.ticket} />}

          {(order.target_price !== null || order.stop_price !== null) && (
            <p
              className="flex flex-wrap items-center gap-1.5 text-[11px] mt-1.5 tabular"
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
              className="text-xs mt-1.5 leading-relaxed max-w-3xl break-words"
              style={{ color: "var(--text-secondary)" }}
            >
              {order.thesis}
            </p>
          )}

          {executed && executedTotal !== null && (
            <p
              className="text-xs mt-2 tabular break-words"
              style={{ color: "var(--text-secondary)" }}
            >
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
          <div className="grid grid-cols-2 gap-2 md:flex md:items-center md:shrink-0">
            <button
              onClick={onExecute}
              className="flex items-center justify-center gap-1.5 min-h-11 px-3.5 py-2 rounded-md text-xs font-semibold md:min-h-0"
              style={{ background: "var(--success)", color: "white" }}
            >
              <Check size={12} />
              Executei
            </button>
            <button
              onClick={onSkip}
              className="flex items-center justify-center gap-1.5 min-h-11 px-3 py-2 rounded-md text-xs font-medium md:min-h-0"
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

/**
 * The broker ticket. This is what the client retypes into Agora at the moment
 * of buying, so it gets the loudest treatment on the card: ticker, quantity
 * and price on one tabular line, one line per B3 order book.
 */
const Ticket = ({ lines }: { lines: TicketLine[] }) => {
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(null), 1800);
    return () => clearTimeout(t);
  }, [copied]);

  if (lines.length === 0) return null;

  const copy = async (line: TicketLine) => {
    const text =
      line.book === "aplicação"
        ? `${line.ticker} ${line.price.toFixed(2)}`
        : `${line.ticker} ${formatNumber(line.quantity)} ${line.price.toFixed(2)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(line.ticker);
    } catch {
      // Clipboard is blocked outside a secure context; the numbers are on
      // screen anyway, so a failed copy is not worth an error state.
    }
  };

  return (
    <div className="mt-3 space-y-1.5">
      {lines.map((line) => (
        <div
          key={`${line.ticker}-${line.book}`}
          className="flex items-center gap-3 flex-wrap rounded-md px-3 py-2.5"
          style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
        >
          {line.book === "aplicação" ? (
            <span
              className="text-sm tabular font-semibold"
              style={{ color: "var(--text-primary)" }}
            >
              Aplicar {formatBRL(line.price)}
            </span>
          ) : (
            <>
              <span
                className="text-base font-semibold tracking-tight"
                style={{ color: "var(--text-primary)" }}
              >
                {line.ticker}
              </span>
              <span className="text-sm tabular" style={{ color: "var(--text-primary)" }}>
                <strong>{formatNumber(line.quantity)}</strong> un
              </span>
              <span className="text-sm tabular" style={{ color: "var(--text-primary)" }}>
                {formatBRL(line.price)}
              </span>
              <span className="text-xs tabular" style={{ color: "var(--text-muted)" }}>
                = {formatBRL(line.total_brl)} · {line.book}
              </span>
            </>
          )}
          <button
            type="button"
            onClick={() => copy(line)}
            aria-label={`Copiar ordem de ${line.ticker}`}
            className="ml-auto flex items-center gap-1.5 min-h-11 px-2.5 rounded-md text-[11px] font-medium md:min-h-0 md:py-1.5"
            style={{ color: copied === line.ticker ? "var(--success)" : "var(--text-muted)" }}
          >
            {copied === line.ticker ? <Check size={12} /> : <Copy size={12} />}
            {copied === line.ticker ? "copiado" : "copiar"}
          </button>
        </div>
      ))}
    </div>
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
      // Prefill with what we told them to buy: the common case is confirming
      // the ticket as-is, and an empty form made them retype both numbers.
      setQuantity(
        order.suggested_quantity !== null ? String(order.suggested_quantity) : ""
      );
      setPrice(
        order.reference_price !== null
          ? String(order.reference_price)
          : order.target_price !== null
            ? String(order.target_price)
            : ""
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
      className="p-5 md:p-7 rounded-md max-w-md w-[calc(100%-2rem)] m-4 md:m-0 md:w-full backdrop:bg-black/40"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {order && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <h3
              className="text-2xl tracking-tight min-w-0 break-words"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              Executei {order.ticker}
            </h3>
            {/* 44px tap target on phones; the desktop icon button is untouched. */}
            <button
              type="button"
              onClick={onClose}
              aria-label="Fechar"
              className="flex items-center justify-center min-h-11 min-w-11 shrink-0 p-1.5 rounded-md md:block md:min-h-0 md:min-w-0"
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

          <div className="flex flex-col gap-3 pt-1 md:flex-row">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center justify-center gap-2 min-h-11 w-full px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40 md:min-h-0 md:w-auto"
              style={{ background: "var(--success)", color: "white" }}
            >
              <Check size={13} />
              {submitting ? "Registrando..." : "Confirmar execução"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex items-center justify-center min-h-11 w-full px-5 py-2.5 rounded-md text-sm font-medium md:min-h-0 md:w-auto"
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
      className="p-5 md:p-7 rounded-md max-w-md w-[calc(100%-2rem)] m-4 md:m-0 md:w-full backdrop:bg-black/40"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {order && (
        <form onSubmit={handleSubmit} className="space-y-4">
          <h3
            className="text-2xl tracking-tight break-words"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Pular {order.ticker}?
          </h3>
          <p className="text-xs -mt-2" style={{ color: "var(--text-muted)" }}>
            A ordem fica registrada como não executada, sem efeito na carteira.
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
              // text-base keeps iOS from zooming the viewport on focus.
              className="w-full px-4 py-2.5 rounded-md text-base outline-none md:text-sm"
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

          <div className="flex flex-col gap-3 pt-1 md:flex-row">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center justify-center gap-2 min-h-11 w-full px-5 py-2.5 rounded-md text-sm font-semibold disabled:opacity-40 md:min-h-0 md:w-auto"
              style={{ background: "var(--accent)", color: "white" }}
            >
              <SkipForward size={13} />
              {submitting ? "Registrando..." : "Pular ordem"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex items-center justify-center min-h-11 w-full px-5 py-2.5 rounded-md text-sm font-medium md:min-h-0 md:w-auto"
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
      // text-base keeps iOS from zooming the viewport on focus.
      className="w-full px-4 py-2.5 rounded-md text-base outline-none tabular md:text-sm"
      style={{
        background: "var(--bg-secondary)",
        border: "1px solid var(--border)",
        color: "var(--text-primary)",
      }}
    />
  </div>
);
