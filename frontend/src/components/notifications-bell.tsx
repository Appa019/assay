"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Bell,
  CheckCheck,
  ClipboardList,
  FileText,
  MessagesSquare,
  Receipt,
  Settings,
  Settings2,
  X,
} from "lucide-react";
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
  type NotificationKind,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const KIND_ICON: Record<NotificationKind, typeof Bell> = {
  orders: ClipboardList,
  review: FileText,
  alert: AlertTriangle,
  ledger: Receipt,
  chat: MessagesSquare,
  system: Settings2,
};

const LEVEL_COLOR: Record<AppNotification["level"], string> = {
  info: "var(--text-muted)",
  success: "var(--success)",
  warning: "var(--warning, var(--accent))",
  error: "var(--danger)",
};

/** Poll slowly: these arrive from crons, minutes apart at best. */
const POLL_MS = 60_000;

/**
 * The inbox. Everything the system has to say used to go to Telegram, which
 * the client never opened — so it lives here, in the app, and the row survives
 * even when the push notification does not.
 *
 * Rendered twice by the shell: inline in the desktop sidebar, and as a floating
 * button on phones, where there is no chrome to hang it off.
 */
export const NotificationsBell = ({
  variant,
}: {
  variant: "sidebar" | "floating";
}) => {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const data = await fetchNotifications();
    if (!data) return;
    setItems(data.items);
    setUnread(data.unread);
  }, []);

  // Same split the chat uses: the first load is deferred a tick so it is not a
  // synchronous setState inside the effect, then a slow interval takes over.
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  // Escape closes the panel; the backdrop handles pointer dismissal.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const handleRead = async (item: AppNotification) => {
    if (item.read_at) return;
    setItems((prev) =>
      prev.map((n) =>
        n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n
      )
    );
    setUnread((n) => Math.max(0, n - 1));
    try {
      await markNotificationRead(item.id);
    } catch {
      void load(); // server disagreed; take its word
    }
  };

  const handleReadAll = async () => {
    setUnread(0);
    setItems((prev) =>
      prev.map((n) => (n.read_at ? n : { ...n, read_at: new Date().toISOString() }))
    );
    try {
      await markAllNotificationsRead();
    } catch {
      void load();
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={unread > 0 ? `Avisos, ${unread} não lidos` : "Avisos"}
        className={
          variant === "sidebar"
            ? "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium w-full"
            : "md:hidden fixed right-4 z-40 flex items-center justify-center h-11 w-11 rounded-full"
        }
        style={
          variant === "sidebar"
            ? { color: "var(--text-secondary)" }
            : {
                top: "calc(env(safe-area-inset-top) + 0.75rem)",
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                color: "var(--text-secondary)",
              }
        }
      >
        <span className="relative flex items-center">
          <Bell size={17} strokeWidth={1.8} />
          {unread > 0 && (
            <span
              className="absolute -top-1.5 -right-2 text-[10px] font-semibold tabular px-1.5 rounded-full leading-[15px]"
              style={{ background: "var(--accent)", color: "white" }}
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </span>
        {variant === "sidebar" && "Avisos"}
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-50 bg-black/40"
            />
            <motion.aside
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 320, damping: 34 }}
              role="dialog"
              aria-modal="true"
              aria-labelledby="notifications-title"
              className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md flex flex-col"
              style={{
                background: "var(--bg-card)",
                borderLeft: "1px solid var(--border)",
                paddingTop: "env(safe-area-inset-top)",
                paddingBottom: "env(safe-area-inset-bottom)",
              }}
            >
              <header
                className="flex items-center justify-between gap-3 px-5 py-4 border-b shrink-0"
                style={{ borderColor: "var(--border)" }}
              >
                <h2
                  id="notifications-title"
                  className="text-2xl tracking-tight"
                  style={{
                    fontFamily: "var(--font-heading)",
                    color: "var(--text-primary)",
                  }}
                >
                  Avisos
                </h2>
                <div className="flex items-center gap-1">
                  {unread > 0 && (
                    <button
                      type="button"
                      onClick={handleReadAll}
                      className="flex items-center gap-1.5 min-h-11 px-2.5 rounded-md text-[11px] font-medium md:min-h-0 md:py-1.5"
                      style={{ color: "var(--text-muted)" }}
                    >
                      <CheckCheck size={13} />
                      Marcar todos
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    // Focus lands inside the panel so Escape and Tab work at once.
                    autoFocus
                    aria-label="Fechar"
                    className="flex items-center justify-center min-h-11 min-w-11 rounded-md md:min-h-0 md:min-w-0 md:p-1.5"
                    style={{ color: "var(--text-muted)" }}
                  >
                    <X size={16} />
                  </button>
                </div>
              </header>

              <div className="flex-1 overflow-y-auto overscroll-contain">
                {items.length === 0 ? (
                  <p
                    className="px-5 py-10 text-sm leading-relaxed"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Nada por aqui ainda. Revisões do comitê, alertas de alvo e
                    stop, folhas de ordens e falhas de rotina aparecem nesta
                    lista.
                  </p>
                ) : (
                  <ul>
                    {items.map((item) => (
                      <NotificationRow
                        key={item.id}
                        item={item}
                        onOpen={() => {
                          void handleRead(item);
                          setOpen(false);
                        }}
                        onRead={() => void handleRead(item)}
                      />
                    ))}
                  </ul>
                )}
              </div>
              <Link
                href="/configuracoes"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-5 min-h-12 border-t text-[13px] font-medium shrink-0"
                style={{ borderColor: "var(--border)", color: "var(--accent)" }}
              >
                <Settings size={15} />
                Ajustes: avisos no celular e cartões
              </Link>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
};

const NotificationRow = ({
  item,
  onOpen,
  onRead,
}: {
  item: AppNotification;
  onOpen: () => void;
  onRead: () => void;
}) => {
  const Icon = KIND_ICON[item.kind];
  const unread = item.read_at === null;
  const [expanded, setExpanded] = useState(false);
  const hasMore = item.body.length > 160 && item.body !== item.title;

  return (
    <li
      className="border-b last:border-b-0"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="px-5 py-4 flex gap-3">
        <Icon
          size={15}
          strokeWidth={1.9}
          className="mt-0.5 shrink-0"
          style={{ color: LEVEL_COLOR[item.level] }}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <p
              className="text-sm leading-snug break-words flex-1"
              style={{
                color: "var(--text-primary)",
                fontWeight: unread ? 600 : 400,
              }}
            >
              {item.title}
            </p>
            {unread && (
              <span
                aria-hidden
                className="mt-1.5 h-1.5 w-1.5 rounded-full shrink-0"
                style={{ background: "var(--accent)" }}
              />
            )}
          </div>

          {item.body !== item.title && (
            <p
              className="text-xs mt-1.5 leading-relaxed break-words whitespace-pre-wrap"
              style={{ color: "var(--text-secondary)" }}
            >
              {expanded || !hasMore ? item.body : `${item.body.slice(0, 160)}…`}
            </p>
          )}

          <div className="flex items-center gap-3 mt-2 flex-wrap">
            <span className="text-[11px] tabular" style={{ color: "var(--text-muted)" }}>
              {formatDateTime(item.created_at)}
            </span>
            {hasMore && (
              <button
                type="button"
                onClick={() => {
                  setExpanded((v) => !v);
                  onRead();
                }}
                className="text-[11px] font-medium"
                style={{ color: "var(--accent)" }}
              >
                {expanded ? "menos" : "ler tudo"}
              </button>
            )}
            {item.url && (
              <Link
                href={item.url}
                onClick={onOpen}
                className="text-[11px] font-medium"
                style={{ color: "var(--accent)" }}
              >
                abrir
              </Link>
            )}
          </div>
        </div>
      </div>
    </li>
  );
};
