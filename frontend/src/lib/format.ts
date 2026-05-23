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
