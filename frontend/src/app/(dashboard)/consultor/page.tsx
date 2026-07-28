"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Paperclip, RotateCcw, Send, WifiOff, X } from "lucide-react";
import {
  ApiError,
  fetchChat,
  resetChatSession,
  sendChatMessage,
  uploadChatAttachment,
  type ChatMessage,
} from "@/lib/api";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { parseLocalDate } from "@/lib/format";

const POLL_IDLE_MS = 12_000;
const POLL_BUSY_MS = 2_500;

const timeLabel = (iso: string): string =>
  parseLocalDate(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

const ConsultorPage = () => {
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [attachment, setAttachment] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const state = await fetchChat();
      setMessages(state.messages);
      setBusy(state.busy || state.messages.some((m) => m.status === "running"));
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  // Poll fast while a turn is in flight, slowly otherwise — a reply can also
  // arrive from Telegram, so the page keeps watching even when idle.
  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const interval = setInterval(() => void load(), busy ? POLL_BUSY_MS : POLL_IDLE_MS);
    return () => clearInterval(interval);
  }, [busy, load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = async () => {
    const text = draft.trim();
    if (busy || uploading) return;
    if (!text && !attachment) return;
    setError(null);

    // An attachment carries the typed text as its caption, so one tap sends
    // "aqui está o cupom" together with the photo.
    if (attachment) {
      const file = attachment;
      setUploading(true);
      setDraft("");
      setAttachment(null);
      try {
        const state = await uploadChatAttachment(file, text);
        setMessages(state.messages);
        setBusy(true);
      } catch (err) {
        setAttachment(file);
        setDraft(text);
        setError(
          err instanceof ApiError && err.status === 413
            ? "Arquivo grande demais (limite de 20 MB)."
            : err instanceof Error
              ? err.message
              : "Não foi possível enviar o arquivo.",
        );
      } finally {
        setUploading(false);
      }
      return;
    }

    setDraft("");
    try {
      const state = await sendChatMessage(text);
      setMessages(state.messages);
      setBusy(true);
    } catch (err) {
      setDraft(text);
      if (err instanceof ApiError && err.status === 409) {
        setError("Ainda estou respondendo a anterior.");
      } else {
        setError(err instanceof Error ? err.message : "Não foi possível enviar.");
      }
    }
  };

  const reset = async () => {
    if (busy) return;
    try {
      await resetChatSession();
      setError(null);
    } catch {
      setError("Não consegui reiniciar a sessão.");
    }
  };

  return (
    <div className="flex flex-col" style={{ minHeight: "calc(100dvh - 8rem)" }}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2
            className="text-[1.7rem] md:text-3xl leading-tight"
            style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
          >
            Consultor
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void reset()}
          disabled={busy}
          title="Começa uma sessão nova. A memória sobre você continua."
          className="flex min-h-[2.75rem] shrink-0 items-center gap-2 rounded-md border px-3.5 text-[13px] font-medium disabled:opacity-40"
          style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
        >
          <RotateCcw size={14} strokeWidth={1.9} />
          Nova sessão
        </button>
      </header>

      {offline && (
        <div
          className="mt-5 flex items-start gap-3 rounded-lg border p-4 text-sm"
          style={{
            borderColor: "var(--danger)",
            background: "var(--danger-light)",
            color: "var(--text-primary)",
          }}
        >
          <WifiOff size={17} strokeWidth={1.9} className="mt-0.5 shrink-0" />
          <span>Backend fora do ar — a conversa não está atualizando.</span>
        </div>
      )}

      <div className="mt-6 flex-1">
        {messages === null && (
          <div className="flex flex-col gap-3">
            {[0, 1].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg"
                style={{ background: "var(--bg-secondary)" }}
              />
            ))}
          </div>
        )}

        {messages?.length === 0 && (
          <div
            className="rounded-lg border p-5"
            style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
          >
            <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              Fale como você falaria com um consultor. Ele registra gastos
              (&ldquo;gastei 42 no mercado&rdquo;), responde sobre a carteira,
              lê o cupom que você fotografar e dispara o comitê quando você
              pedir um aporte.
            </p>
          </div>
        )}

        <div className="flex flex-col gap-5">
          {messages?.map((message) => (
            <Turn key={message.id} message={message} />
          ))}
        </div>
        <div ref={bottomRef} />
      </div>

      <div
        className="sticky bottom-0 mt-6 pt-3"
        style={{ background: "var(--bg-primary)" }}
      >
        {error && (
          <p className="mb-2 text-[13px]" style={{ color: "var(--danger)" }}>
            {error}
          </p>
        )}
        {attachment && (
          <div
            className="mb-2 flex items-center gap-2 rounded-md border px-3 py-2"
            style={{ borderColor: "var(--accent)", background: "var(--accent-light)" }}
          >
            <Paperclip size={14} strokeWidth={1.9} style={{ color: "var(--accent-strong)" }} />
            <span
              className="min-w-0 flex-1 truncate text-[13px]"
              style={{ color: "var(--text-primary)" }}
            >
              {attachment.name}
            </span>
            <button
              type="button"
              onClick={() => setAttachment(null)}
              aria-label="Remover anexo"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full"
              style={{ color: "var(--text-secondary)" }}
            >
              <X size={15} strokeWidth={2} />
            </button>
          </div>
        )}

        <div className="flex items-end gap-2">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept="image/*,.pdf,.csv,.txt,.xls,.xlsx,.ofx"
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null;
              setAttachment(file);
              setError(null);
              // Reset so picking the same file twice still fires onChange.
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={busy || uploading}
            aria-label="Anexar foto ou arquivo"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-md border disabled:opacity-40"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            <Paperclip size={18} strokeWidth={1.9} />
          </button>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter is a newline. On a phone the virtual
              // keyboard sends a plain Enter, which is what you want here.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            placeholder={
              attachment ? "Quer dizer algo sobre o arquivo?" : "Pergunte, registre um gasto, peça um aporte…"
            }
            aria-label="Mensagem"
            className="min-h-[2.75rem] w-full min-w-0 resize-none rounded-md border bg-transparent px-3.5 py-3 text-base outline-none"
            style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={busy || uploading || (draft.trim().length === 0 && !attachment)}
            aria-label="Enviar"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-md disabled:opacity-40"
            style={{ background: "var(--accent)", color: "white" }}
          >
            {busy || uploading ? (
              <Loader2 size={17} className="animate-spin" />
            ) : (
              <Send size={17} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

/** One line of the transcript. Deliberately not a bubble-with-tail chat UI. */
const Turn = ({ message }: { message: ChatMessage }) => {
  const isUser = message.role === "user";
  const running = message.status === "running";
  const failed = message.status === "failed";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div
          className="max-w-[85%] rounded-lg px-4 py-2.5"
          style={{ background: "var(--accent-light)", color: "var(--text-primary)" }}
        >
          <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">
            {message.content}
          </p>
          <p className="mt-1 text-[10px]" style={{ color: "var(--text-muted)" }}>
            {timeLabel(message.created_at)}
            {message.channel === "telegram" ? " · Telegram" : ""}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0">
      {running ? (
        <p
          className="flex items-center gap-2 text-sm"
          style={{ color: "var(--text-muted)" }}
        >
          <Loader2 size={14} className="animate-spin" />
          Pensando…
        </p>
      ) : (
        <>
          <div
            className="min-w-0 text-[15px]"
            style={{ color: failed ? "var(--danger)" : "var(--text-primary)" }}
          >
            {failed ? (
              <p className="leading-relaxed break-words">{message.content}</p>
            ) : (
              <MarkdownViewer content={message.content} withToc={false} />
            )}
          </div>
          <p className="mt-1.5 text-[10px]" style={{ color: "var(--text-muted)" }}>
            {timeLabel(message.created_at)}
          </p>
        </>
      )}
    </div>
  );
};

export default ConsultorPage;
