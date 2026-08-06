export type BRLOptions = {
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
};

export const formatBRL = (
  value: number | null | undefined,
  options?: BRLOptions,
): string => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: options?.minimumFractionDigits ?? 2,
    maximumFractionDigits: options?.maximumFractionDigits ?? 2,
  }).format(value);
};

export const formatBRLCompact = (value: number | null | undefined): string =>
  formatBRL(value, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

/**
 * pt-BR digits with no currency symbol — for rows that carry their own +/−
 * sign. Stripping "R$" off formatBRL by hand broke on the non-breaking space
 * Intl inserts after the symbol.
 */
export const formatAmount = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", {
    style: "decimal",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

export const formatNumber = (value: number | null | undefined): string => {
  if (value === null || value === undefined) return "—";
  return value >= 1
    ? new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(value)
    : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 8 }).format(value);
};

export const formatPercent = (
  value: number | null | undefined,
  digits = 1,
): string => {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
};

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Parse an ISO string as a LOCAL date. `new Date("2026-05-11")` is parsed as
 * UTC midnight, which shifts the displayed day back in negative-offset
 * timezones (e.g. Brazil). Date-only strings are therefore expanded manually.
 * Full datetimes WITHOUT a timezone come from the backend as naive UTC — the
 * native parser would read them as local time and display timestamps three
 * hours ahead, so a "Z" is appended before parsing.
 */
const NAIVE_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export const parseLocalDate = (value: string): Date => {
  if (DATE_ONLY_RE.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
  }
  if (NAIVE_DATETIME_RE.test(value)) {
    return new Date(`${value}Z`);
  }
  return new Date(value);
};

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return "—";
  return parseLocalDate(value).toLocaleDateString("pt-BR");
};

export const formatDateLong = (value: string | null | undefined): string => {
  if (!value) return "—";
  return parseLocalDate(value).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
};

export const formatDateTime = (value: string | null | undefined): string => {
  if (!value) return "—";
  return parseLocalDate(value).toLocaleString("pt-BR");
};

/** Days elapsed since an ISO date, ignoring the time component. */
export const daysSince = (value: string): number => {
  const start = parseLocalDate(value);
  start.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.floor((today.getTime() - start.getTime()) / 86_400_000);
};

/**
 * Hide the machine-readable ```json block appended to the committee's closing
 * summary — it exists for order ingestion, not for reading. The client sees
 * only the clean "how much and where" structure.
 */
export const stripMachineBlocks = (text: string): string =>
  text
    .replace(/\n*-{3,}\s*\n+```json[\s\S]*?```\s*/g, "\n")
    .replace(/```json[\s\S]*?```/g, "")
    .trim();
