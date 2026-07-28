"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchCashflow,
  fetchCashflowSummary,
  type CashflowEntry,
  type CashflowSummary,
} from "@/lib/api";

/**
 * Entries and totals for one month, always fetched as a pair so the list and
 * the header can never disagree after a write.
 */
export const useCashflow = (month: string) => {
  const [entries, setEntries] = useState<CashflowEntry[] | null>(null);
  const [summary, setSummary] = useState<CashflowSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [list, totals] = await Promise.all([
        fetchCashflow(month),
        fetchCashflowSummary(month),
      ]);
      setEntries(list);
      setSummary(totals);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar finanças");
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    setLoading(true);
    void refresh();
  }, [refresh]);

  return { entries, summary, loading, error, refresh };
};
