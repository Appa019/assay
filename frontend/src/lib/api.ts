export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type AssetClass = "fixed_income" | "stocks" | "crypto";

export type ContributionStatus =
  | "pending"
  | "ready"
  | "in_progress"
  | "completed";

export type PromptKey =
  | "macro"
  | "selection"
  | "equity_diligence"
  | "crypto_diligence"
  | "decision"
  | "research"; // legacy: contributions created before the 5-stage split

export type Asset = {
  id: string;
  ticker: string;
  name: string | null;
  asset_class: AssetClass;
  quantity: number;
  avg_price: number;
  current_price: number | null;
  entry_date: string;
  thesis: string | null;
  target_price: number | null;
  stop_price: number | null;
  // Sell lock resolved by the backend, per class and per lot (stocks 30d,
  // crypto 7d, CDB none). Never re-derive the rule here.
  lock_days_total: number;
  lock_days_left: number;
  created_at: string;
  updated_at: string;
};

export type AssetCreate = {
  ticker: string;
  name?: string;
  asset_class: AssetClass;
  quantity: number;
  avg_price: number;
  current_price?: number;
  entry_date?: string;
};

export type AssetUpdate = Partial<Pick<Asset, "name">> & {
  quantity?: number;
  avg_price?: number;
  current_price?: number;
};

export type AllocationBreakdown = {
  total_value: number;
  fixed_income: number;
  stocks: number;
  crypto: number;
  fixed_income_pct: number;
  stocks_pct: number;
  crypto_pct: number;
};

export type PortfolioSummary = {
  total_value: number;
  allocation: AllocationBreakdown;
  target_allocation: { fixed_income: number; stocks: number; crypto: number };
  deviation: { fixed_income: number; stocks: number; crypto: number };
  holding_lock_days: { fixed_income: number; stocks: number; crypto: number };
  assets: Asset[];
};

export type SaleResult = {
  ticker: string;
  quantity: number;
  price: number;
  sale_value: number;
  asset_class: AssetClass;
  message: string;
};

export type Prompt = {
  id: string;
  prompt_order: number;
  prompt_key: PromptKey;
  title: string;
  description: string;
  content: string;
  response: string | null;
  responded_at: string | null;
  cost_usd: number | null;
  duration_s: number | null;
  num_turns: number | null;
};

export type Contribution = {
  id: string;
  amount_brl: number;
  status: ContributionStatus;
  macro_snapshot: Record<string, unknown> | null;
  portfolio_snapshot: Record<string, unknown> | null;
  final_summary: string | null;
  notes: string | null;
  created_at: string;
  completed_at: string | null;
  prompts: Prompt[];
};

export type ContributionListItem = {
  id: string;
  amount_brl: number;
  status: ContributionStatus;
  created_at: string;
  completed_at: string | null;
  prompts_total: number;
  prompts_answered: number;
};

export type MacroSnapshot = {
  macro: {
    selic: number | null;
    ipca_12m: number | null;
    cdi: number | null;
    usd_brl: number | null;
  };
  ibovespa: {
    level: number | null;
    day_change_pct: number | null;
    month_return_pct: number | null;
    volume: number | null;
  };
  crypto_global: {
    btc_dominance: number | null;
    eth_dominance: number | null;
    total_market_cap_usd: number | null;
    total_volume_24h_usd: number | null;
    market_cap_change_24h_pct: number | null;
  };
  fear_greed_index: number | null;
  captured_at: string;
  warnings: string[];
  sources: Record<string, string>;
};

export type CadenceStatus = {
  last_contribution_date: string | null;
  days_since_last: number | null;
  total_contributions: number;
};

/** API error carrying the HTTP status so callers can branch on 404/409. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

const json = async <T>(res: Response): Promise<T> => {
  if (!res.ok) {
    let detail = "Erro na API";
    try {
      const body = await res.json();
      detail = (body as { detail?: string }).detail ?? detail;
    } catch {
      try {
        detail = (await res.text()) || detail;
      } catch {
        // keep default detail
      }
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
};

export const fetchPortfolio = async (): Promise<PortfolioSummary> =>
  json<PortfolioSummary>(await fetch(`${API_BASE}/api/portfolio`));

export const fetchAssets = async (): Promise<Asset[]> =>
  json<Asset[]>(await fetch(`${API_BASE}/api/portfolio/assets`));

export const createAsset = async (payload: AssetCreate): Promise<Asset> =>
  json<Asset>(
    await fetch(`${API_BASE}/api/portfolio/assets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );

export const updateAsset = async (
  id: string,
  payload: AssetUpdate
): Promise<Asset> =>
  json<Asset>(
    await fetch(`${API_BASE}/api/portfolio/assets/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );

export const sellAsset = async (id: string): Promise<SaleResult> =>
  json<SaleResult>(
    await fetch(`${API_BASE}/api/portfolio/assets/${id}/sell`, {
      method: "POST",
    })
  );

export const deleteAsset = async (id: string): Promise<Asset> =>
  json<Asset>(
    await fetch(`${API_BASE}/api/portfolio/assets/${id}`, {
      method: "DELETE",
    })
  );

export type RefreshResult = {
  updated: number;
  warnings: string[];
};

export const refreshPortfolioPrices = async (): Promise<RefreshResult> =>
  json<RefreshResult>(
    await fetch(`${API_BASE}/api/portfolio/refresh`, { method: "POST" })
  );

export type PortfolioHistoryPoint = {
  snapshot_date: string;
  total_value: number;
  fixed_income: number;
  stocks: number;
  crypto: number;
};

/**
 * Equity-curve snapshots. Returns null when the endpoint is not available yet
 * (404) so callers can hide the section gracefully.
 */
export const fetchPortfolioHistory = async (
  days = 365
): Promise<PortfolioHistoryPoint[] | null> => {
  try {
    return await json<PortfolioHistoryPoint[]>(
      await fetch(`${API_BASE}/api/portfolio/history?days=${days}`)
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
};

export type TradeSide = "buy" | "sell";

export type Trade = {
  id: string;
  ticker: string;
  asset_class: AssetClass;
  side: TradeSide;
  quantity: number;
  price: number;
  total_brl: number;
  realized_pnl_brl: number | null;
  realized_pnl_pct: number | null;
  lot_entry_date: string | null;
  executed_at: string;
};

/** Trade log. Returns null on 404 so callers can hide the section gracefully. */
export const fetchTrades = async (): Promise<Trade[] | null> => {
  try {
    return await json<Trade[]>(await fetch(`${API_BASE}/api/portfolio/trades`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
};

/* ── Orders (folha de ordens do comitê) ────────────────────────────── */

export type OrderStatus = "pending" | "executed" | "skipped";

/** One line of the broker ticket, already split by B3 order book. */
export type TicketLine = {
  ticker: string;
  quantity: number;
  price: number;
  book: string;
  total_brl: number;
};

export type Order = {
  id: string;
  contribution_id: string;
  ticker: string;
  asset_class: AssetClass;
  amount_brl: number;
  pct_of_contribution: number | null;
  target_price: number | null;
  stop_price: number | null;
  thesis: string | null;
  status: OrderStatus;
  suggested_quantity: number | null;
  reference_price: number | null;
  priced_at: string | null;
  ticket: TicketLine[];
  executed_quantity: number | null;
  executed_price: number | null;
  executed_at: string | null;
  created_at: string;
};

/** Order sheet. Returns null on 404 so callers can hide the panel gracefully. */
export const fetchOrders = async (status?: OrderStatus): Promise<Order[] | null> => {
  const qs = status ? `?status=${status}` : "";
  try {
    return await json<Order[]>(await fetch(`${API_BASE}/api/orders${qs}`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
};

export const executeOrder = async (
  id: string,
  quantity: number,
  price: number
): Promise<Order> =>
  json<Order>(
    await fetch(`${API_BASE}/api/orders/${id}/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quantity, price }),
    })
  );

export const skipOrder = async (id: string, reason?: string): Promise<Order> =>
  json<Order>(
    await fetch(`${API_BASE}/api/orders/${id}/skip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || undefined }),
    })
  );

/* ── Avisos (inbox do app — substituiu o Telegram) ─────────────────── */

export type NotificationKind =
  | "orders"
  | "review"
  | "alert"
  | "ledger"
  | "system"
  | "chat";

export type NotificationLevel = "info" | "success" | "warning" | "error";

export type AppNotification = {
  id: string;
  kind: NotificationKind;
  level: NotificationLevel;
  title: string;
  body: string;
  url: string | null;
  read_at: string | null;
  created_at: string;
};

export type NotificationList = {
  items: AppNotification[];
  unread: number;
};

/** Returns null on failure so the bell can stay quiet instead of erroring. */
export const fetchNotifications = async (
  limit = 50
): Promise<NotificationList | null> => {
  try {
    return await json<NotificationList>(
      await fetch(`${API_BASE}/api/notifications?limit=${limit}`)
    );
  } catch {
    return null;
  }
};

export const markNotificationRead = async (
  id: string
): Promise<AppNotification> =>
  json<AppNotification>(
    await fetch(`${API_BASE}/api/notifications/${id}/read`, { method: "POST" })
  );

export const markAllNotificationsRead = async (): Promise<number> => {
  const data = await json<{ marked: number }>(
    await fetch(`${API_BASE}/api/notifications/read-all`, { method: "POST" })
  );
  return data.marked;
};

/* ── Benchmark (TWR vs CDI · IBOV · BTC, rebased 100) ──────────────── */

export type BenchmarkPoint = {
  date: string;
  portfolio: number;
  cdi: number | null;
  ibov: number | null;
  btc: number | null;
};

export type BenchmarkResponse = {
  series: BenchmarkPoint[];
  note?: string;
};

/** Benchmark series. Returns null on 404 so callers can hide it gracefully. */
export const fetchBenchmark = async (
  days = 365
): Promise<BenchmarkResponse | null> => {
  try {
    return await json<BenchmarkResponse>(
      await fetch(`${API_BASE}/api/portfolio/benchmark?days=${days}`)
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
};

/* ── Tax (mapa simplificado de IR) ─────────────────────────────────── */

export type TaxMonthClass = {
  sales_brl: number;
  net_gain_brl: number;
  exempt: boolean;
  loss_carry_used_brl: number;
  tax_due_brl: number;
  darf_below_minimum: boolean;
};

export type FixedIncomeTaxInfo = {
  ticker: string;
  income_brl: number;
  days_held: number | null;
  withheld_rate_pct: number | null;
};

export type TaxMonth = {
  month: string;
  stocks: TaxMonthClass;
  crypto: TaxMonthClass;
  fixed_income_info?: FixedIncomeTaxInfo[];
};

export type YearEndPosition = {
  ticker: string;
  asset_class: AssetClass;
  quantity: number;
  cost_basis_brl: number;
};

export type TaxReport = {
  year: number;
  months: TaxMonth[];
  total_darf_brl: number;
  loss_carryforward_brl: { stocks: number; crypto: number };
  year_end_positions: YearEndPosition[];
  notes: string[];
};

/** Throws ApiError (422 for out-of-range years) — caller shows the detail. */
export const fetchTaxReport = async (year: number): Promise<TaxReport> =>
  json<TaxReport>(await fetch(`${API_BASE}/api/tax/${year}`));

export const fetchMacro = async (): Promise<MacroSnapshot> =>
  json<MacroSnapshot>(await fetch(`${API_BASE}/api/macro`));

export const fetchCadence = async (): Promise<CadenceStatus> =>
  json<CadenceStatus>(await fetch(`${API_BASE}/api/cadence`));

export const createContribution = async (
  amount_brl: number,
  notes?: string,
  run = false
): Promise<Contribution> =>
  json<Contribution>(
    await fetch(`${API_BASE}/api/contributions?run=${run}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount_brl, notes }),
    })
  );

export const runContribution = async (id: string): Promise<Contribution> =>
  json<Contribution>(
    await fetch(`${API_BASE}/api/contributions/${id}/run`, {
      method: "POST",
    })
  );

export const listContributions = async (): Promise<ContributionListItem[]> =>
  json<ContributionListItem[]>(await fetch(`${API_BASE}/api/contributions`));

export const fetchContribution = async (id: string): Promise<Contribution> =>
  json<Contribution>(await fetch(`${API_BASE}/api/contributions/${id}`));

export const savePromptResponse = async (
  contributionId: string,
  promptKey: PromptKey,
  response: string
): Promise<Prompt> =>
  json<Prompt>(
    await fetch(
      `${API_BASE}/api/contributions/${contributionId}/prompts/${promptKey}/response`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      }
    )
  );

export const finalizeContribution = async (
  id: string,
  final_summary?: string
): Promise<Contribution> =>
  json<Contribution>(
    await fetch(`${API_BASE}/api/contributions/${id}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ final_summary }),
    })
  );

export const deleteContribution = async (id: string): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/contributions/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Erro ao deletar aporte");
};

export type ReportKind = "weekly" | "maturity" | "monthly";

export type ReportListItem = {
  id: string;
  kind: ReportKind;
  title: string;
  cost_usd: number;
  created_at: string;
};

export type ReportStep = { title: string; response: string };

export type ReportRead = {
  id: string;
  kind: ReportKind;
  title: string;
  content: string;
  cost_usd: number;
  session_id: string | null;
  steps: ReportStep[] | null;
  created_at: string;
};

export const listReports = async (kind?: ReportKind): Promise<ReportListItem[]> => {
  const qs = kind ? `?kind=${kind}` : "";
  return json<ReportListItem[]>(await fetch(`${API_BASE}/api/reports${qs}`));
};

export const fetchReport = async (id: string): Promise<ReportRead> =>
  json<ReportRead>(await fetch(`${API_BASE}/api/reports/${id}`));

// ── Personal cashflow (day-to-day expenses and income) ────────────────────

export type CashflowKind = "expense" | "income";
export type CashflowSource = "chat" | "bot" | "api";
/** Which pot of money moved: bank account, or the VR/VA benefit cards. */
export type CashflowWallet = "conta" | "vr" | "va";

export type CashflowEntry = {
  id: string;
  kind: CashflowKind;
  amount_brl: number;
  category: string;
  description: string | null;
  occurred_on: string;
  source: CashflowSource;
  wallet: CashflowWallet;
  /** Card the purchase went on; null = pix/debit/cash/benefit card. */
  card_id: string | null;
  card_name: string | null;
  /** 1-based installment number and total; null on a single payment. */
  installment_no: number | null;
  installment_count: number | null;
  installment_group: string | null;
  created_at: string;
};

export type CashflowCreate = {
  kind: CashflowKind;
  amount_brl: number;
  category?: string;
  description?: string | null;
  occurred_on?: string;
  wallet?: CashflowWallet;
  /** "none" for pix/debit/cash, a card name, or omitted for the default card. */
  card?: string | null;
  /** Monthly installments (1–48); amount_brl is then the TOTAL. */
  installments?: number;
};

export type CategoryTotal = {
  kind: CashflowKind;
  category: string;
  total_brl: number;
  count: number;
};

export type WalletTotal = {
  wallet: CashflowWallet;
  income_brl: number;
  expense_brl: number;
  net_brl: number;
  entries: number;
};

export type CashflowSummary = {
  month: string;
  income_brl: number;
  expense_brl: number;
  net_brl: number;
  entries: number;
  card_expense_brl: number;
  by_category: CategoryTotal[];
  by_wallet: WalletTotal[];
};

/** Where a forecast number came from — the screen renders the three
 *  differently: committed money reads as fact, a recurrence as expectation. */
export type ForecastOrigin = "realized" | "installment" | "recurring";

export type ForecastLine = {
  origin: ForecastOrigin;
  kind: CashflowKind;
  label: string;
  category: string;
  amount_brl: number;
  /** Day of the month the money moves. */
  day: number;
  card_name: string | null;
  installment_no: number | null;
  installment_count: number | null;
  recurrence_id: string | null;
};

/** A card invoice falling due in the month. Legend only: its purchases
 *  already count on the day they happened, so it is never an outflow. */
export type ForecastInvoice = {
  card_id: string;
  card_name: string;
  closes_on: string;
  due_on: string;
  total_brl: number;
};

export type ForecastMonth = {
  month: string;
  is_current: boolean;
  income_brl: number;
  expense_brl: number;
  net_brl: number;
  realized_income_brl: number;
  realized_expense_brl: number;
  pending_income_brl: number;
  pending_expense_brl: number;
  lines: ForecastLine[];
  invoices: ForecastInvoice[];
};

export type Forecast = {
  generated_on: string;
  months: ForecastMonth[];
  total_income_brl: number;
  total_expense_brl: number;
  total_net_brl: number;
  /** False while nothing is registered — the screen shows how to start
   *  instead of a wall of zeros. */
  has_commitments: boolean;
};

export const fetchForecast = async (months = 6): Promise<Forecast> =>
  json<Forecast>(await fetch(`${API_BASE}/api/cashflow/forecast?months=${months}`));

/** Current month as YYYY-MM in local time, the format the API expects. */
export const currentMonth = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
};

export const fetchCashflow = async (
  month: string,
  kind?: CashflowKind,
): Promise<CashflowEntry[]> => {
  const params = new URLSearchParams({ month, limit: "500" });
  if (kind) params.set("kind", kind);
  return json<CashflowEntry[]>(
    await fetch(`${API_BASE}/api/cashflow?${params.toString()}`),
  );
};

export const fetchCashflowSummary = async (
  month: string,
): Promise<CashflowSummary> =>
  json<CashflowSummary>(
    await fetch(`${API_BASE}/api/cashflow/summary?month=${month}`),
  );

export const createCashflowEntry = async (
  payload: CashflowCreate,
): Promise<CashflowEntry> =>
  json<CashflowEntry>(
    await fetch(`${API_BASE}/api/cashflow`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, source: "api" }),
    }),
  );

export const deleteCashflowEntry = async (
  id: string,
): Promise<CashflowEntry> =>
  json<CashflowEntry>(
    await fetch(`${API_BASE}/api/cashflow/${id}`, { method: "DELETE" }),
  );

/** Delete every monthly row of one installment purchase. */
export const deleteCashflowGroup = async (
  groupId: string,
): Promise<{ deleted: number }> =>
  json<{ deleted: number }>(
    await fetch(`${API_BASE}/api/cashflow/groups/${groupId}`, { method: "DELETE" }),
  );

// ── Credit cards (invoices are computed by the backend, never stored) ───────

export type InvoiceStatus = "open" | "closed" | "past";

export type CardInvoice = {
  card_id: string;
  period_start: string;
  period_end: string;
  closes_on: string;
  due_on: string;
  status: InvoiceStatus;
  total_brl: number;
  entries: number;
};

export type CreditCard = {
  id: string;
  name: string;
  closing_day: number;
  due_day: number;
  is_default: boolean;
  created_at: string;
  open_invoice: CardInvoice;
  last_closed_invoice: CardInvoice | null;
};

export type CardCreate = {
  name: string;
  closing_day: number;
  due_day: number;
  is_default?: boolean;
};

export type CardUpdate = Partial<CardCreate>;

export const fetchCards = async (): Promise<CreditCard[]> =>
  json<CreditCard[]>(await fetch(`${API_BASE}/api/cards`));

export const createCard = async (payload: CardCreate): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

export const updateCard = async (
  id: string,
  payload: CardUpdate,
): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

export const deleteCard = async (id: string): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards/${id}`, { method: "DELETE" }),
  );

// ── Consultant chat (same conversation the Telegram bot talks to) ─────────

export type ChatRole = "user" | "assistant";
export type ChatChannel = "telegram" | "web";
export type ChatTurnStatus = "running" | "done" | "failed";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  channel: ChatChannel;
  status: ChatTurnStatus;
  /** Which model answered, and the tier the router picked for it. */
  model: string | null;
  tier: string | null;
  created_at: string;
};

export type ChatState = {
  busy: boolean;
  messages: ChatMessage[];
};

export const fetchChat = async (limit = 60): Promise<ChatState> =>
  json<ChatState>(await fetch(`${API_BASE}/api/chat?limit=${limit}`));

export const sendChatMessage = async (text: string): Promise<ChatState> =>
  json<ChatState>(
    await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );

export const resetChatSession = async (): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/chat/reset`, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, "Não foi possível reiniciar a sessão");
};

/** Free text → a draft ledger entry. Saves nothing; the user confirms. */
export const classifyCashflow = async (text: string): Promise<CashflowCreate> =>
  json<CashflowCreate>(
    await fetch(`${API_BASE}/api/cashflow/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );

/** How many files one chat message may carry (mirrors the backend cap). */
export const MAX_CHAT_ATTACHMENTS = 3;

/** Send up to 3 photos/documents to the consultant as ONE message/turn. */
export const uploadChatAttachments = async (
  files: File[],
  caption = "",
): Promise<ChatState> => {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("caption", caption);
  // No Content-Type header: the browser must set the multipart boundary.
  return json<ChatState>(
    await fetch(`${API_BASE}/api/chat/upload`, { method: "POST", body: form }),
  );
};

// ── Web Push (PWA notifications on the phone) ─────────────────────────────

export const fetchVapidPublicKey = async (): Promise<string> =>
  (await json<{ key: string }>(await fetch(`${API_BASE}/api/push/vapid-public-key`))).key;

export const savePushSubscription = async (subscription: PushSubscriptionJSON): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/push/subscriptions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription),
  });
  if (!res.ok) throw new ApiError(res.status, "Não foi possível registrar o aparelho");
};

export const deletePushSubscription = async (endpoint: string): Promise<void> => {
  const res = await fetch(`${API_BASE}/api/push/subscriptions`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint }),
  });
  if (!res.ok && res.status !== 404) {
    throw new ApiError(res.status, "Não foi possível remover o aparelho");
  }
};

export const sendPushTest = async (): Promise<number> =>
  (await json<{ sent: number }>(
    await fetch(`${API_BASE}/api/push/test`, { method: "POST" }),
  )).sent;
