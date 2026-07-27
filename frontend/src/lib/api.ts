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

export type ReportKind = "weekly" | "maturity";

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
