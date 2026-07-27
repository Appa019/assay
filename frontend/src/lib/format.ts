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
 * timezones (e.g. Brazil). Date-only strings are therefore expanded manually;
 * full datetimes fall through to the native parser.
 */
export const parseLocalDate = (value: string): Date => {
  if (DATE_ONLY_RE.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
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
