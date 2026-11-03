"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  API_BASE,
  createCard,
  deleteCard,
  sendPushTest,
  updateCard,
  type CreditCard,
} from "@/lib/api";
import { useCards } from "@/hooks/use-cards";
import {
  currentSubscription,
  disablePush,
  enablePush,
  pushEnvironment,
  type PushEnvironment,
} from "@/lib/push";

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

      <NotificationsCard />

      <CardsCard />

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
          <Var name="TARGET_FIXED_INCOME" desc="meta de RF (0.50 = 50%)" />
          <Var name="TARGET_STOCKS" desc="meta de Ações (0.35)" />
          <Var name="TARGET_CRYPTO" desc="meta de Crypto (0.15)" />
          <Var name="MIN_HOLDING_DAYS" desc="trava de venda por lote, ações (default 30)" />
          <Var name="MIN_HOLDING_DAYS_CRYPTO" desc="trava de venda por lote, crypto (default 7)" />
          <Var name="AGENT_MODEL" desc="modelo do comitê (default opus)" />
          <Var name="AGENT_EFFORT" desc="reasoning do comitê (default max)" />
          <Var name="COINGECKO_API_URL" desc="endpoint CoinGecko" />
          <Var name="COINGECKO_API_KEY" desc="opcional, se tiver Pro key" />
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
          <li>Ao final, ele entrega onde investir e quanto, e avisa no app.</li>
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

type PushState = "loading" | "off" | "on" | "busy";

/** Enable/disable Web Push for THIS device, with a real test button. */
const NotificationsCard = () => {
  const [env, setEnv] = useState<PushEnvironment>("unsupported");
  const [state, setState] = useState<PushState>("loading");
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const environment = pushEnvironment();
    setEnv(environment);
    if (environment !== "ready") {
      setState("off");
      return;
    }
    try {
      setState((await currentSubscription()) ? "on" : "off");
    } catch {
      setState("off");
    }
  }, []);

  useEffect(() => {
    // Deferred a tick: the sync part of refresh() sets state, and React's
    // lint (rightly) refuses synchronous setState inside an effect body.
    const timer = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(timer);
  }, [refresh]);

  const toggle = async () => {
    setNote(null);
    setState("busy");
    try {
      if (await currentSubscription()) {
        await disablePush();
        setNote("Notificações desativadas neste aparelho.");
      } else {
        await enablePush();
        setNote("Ativado. Toque em \u201cEnviar teste\u201d para conferir.");
      }
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível alterar.");
    }
    void refresh();
  };

  const test = async () => {
    setNote(null);
    try {
      const sent = await sendPushTest();
      setNote(
        sent > 0
          ? `Teste enviado para ${sent} aparelho(s). A notificação chega em segundos.`
          : "Nenhum aparelho inscrito ainda.",
      );
    } catch {
      setNote("Falha ao enviar o teste.");
    }
  };

  return (
    <section
      className="p-5 md:p-6 rounded-md space-y-3"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <h3
        className="text-xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Notificações
      </h3>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        O aparelho vibra quando o consultor termina uma resposta iniciada pelo
        site. O conteúdo viaja criptografado de ponta a ponta.
      </p>

      {env === "needs-install" && (
        <p className="text-sm" style={{ color: "var(--warning)" }}>
          No iPhone, notificações só funcionam com o app aberto pela Tela de
          Início. Compartilhar → &quot;Adicionar à Tela de Início&quot;, abra por lá e
          volte aqui.
        </p>
      )}
      {env === "unsupported" && (
        <p className="text-sm" style={{ color: "var(--danger)" }}>
          Este navegador não suporta notificações push.
        </p>
      )}

      {env === "ready" && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void toggle()}
            disabled={state === "busy" || state === "loading"}
            className="min-h-[2.75rem] rounded-md px-5 text-sm font-semibold disabled:opacity-40"
            style={{ background: "var(--accent)", color: "white" }}
          >
            {state === "on" ? "Desativar neste aparelho" : "Ativar neste aparelho"}
          </button>
          <button
            type="button"
            onClick={() => void test()}
            disabled={state !== "on"}
            className="min-h-[2.75rem] rounded-md border px-5 text-sm font-medium disabled:opacity-40"
            style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
          >
            Enviar teste
          </button>
        </div>
      )}

      {note && (
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {note}
        </p>
      )}
    </section>
  );
};

const inputStyle = {
  borderColor: "var(--border)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
} as const;

/**
 * The client's credit cards. Closing and due days are what turn ledger rows
 * into invoices; the default card is where an account expense lands when
 * the sentence does not say how it was paid.
 */
const CardsCard = () => {
  const { cards, error, refresh } = useCards();
  const [name, setName] = useState("");
  const [closingDay, setClosingDay] = useState("");
  const [dueDay, setDueDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setNote(null);
    setBusy(true);
    try {
      await createCard({
        name: name.trim(),
        closing_day: Number(closingDay),
        due_day: Number(dueDay),
      });
      setName("");
      setClosingDay("");
      setDueDay("");
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível cadastrar o cartão.");
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async (card: CreditCard) => {
    setNote(null);
    try {
      await updateCard(card.id, { is_default: true });
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível alterar o padrão.");
    }
  };

  const remove = async (card: CreditCard) => {
    setNote(null);
    try {
      await deleteCard(card.id);
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível remover o cartão.");
    }
  };

  return (
    <section
      className="p-5 md:p-6 rounded-md space-y-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <h3
        className="text-xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Cartões
      </h3>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Tudo que você compra vai no cartão padrão, salvo quando disser pix,
        débito ou dinheiro. Fechamento e vencimento definem a fatura.
      </p>

      {cards && cards.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Nenhum cartão ainda. Cadastre o primeiro abaixo.
        </p>
      )}

      {cards && cards.length > 0 && (
        <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
          {cards.map((card) => (
            <li
              key={card.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {card.name}
                  {card.is_default && (
                    <>
                      {" "}
                      <span
                        className="ml-2 text-[10px] uppercase tracking-[0.14em]"
                        style={{ color: "var(--accent)" }}
                      >
                        padrão
                      </span>
                    </>
                  )}
                </p>
                <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                  fecha dia {card.closing_day} · vence dia {card.due_day}
                </p>
              </div>
              <div className="flex gap-2">
                {!card.is_default && (
                  <button
                    type="button"
                    onClick={() => void makeDefault(card)}
                    className="min-h-[2.75rem] rounded-md border px-3 text-[13px] font-medium"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                  >
                    Tornar padrão
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void remove(card)}
                  className="min-h-[2.75rem] rounded-md border px-3 text-[13px] font-medium"
                  style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                >
                  Remover
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(event) => void submit(event)}
        className="grid gap-3 sm:grid-cols-[1fr_6rem_6rem_auto] sm:items-end"
      >
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Nome
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={40}
            placeholder="Nubank"
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Fecha dia
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={31}
            required
            value={closingDay}
            onChange={(event) => setClosingDay(event.target.value)}
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Vence dia
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={31}
            required
            value={dueDay}
            onChange={(event) => setDueDay(event.target.value)}
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="min-h-[2.75rem] rounded-md px-5 text-sm font-semibold disabled:opacity-40"
          style={{ background: "var(--accent)", color: "white" }}
        >
          Cadastrar
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      {note && (
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {note}
        </p>
      )}
    </section>
  );
};
