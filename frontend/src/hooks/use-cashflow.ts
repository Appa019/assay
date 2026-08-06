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
  const [version, setVersion] = useState(0);

  useEffect(() => {
    // Cancellation guard: switching months fast could let January's slow
    // response land AFTER February's and overwrite it — entries from one
    // month under the header of another.
    let cancelled = false;
    const load = async () => {
      setError(null);
      try {
        const [list, totals] = await Promise.all([
          fetchCashflow(month),
          fetchCashflowSummary(month),
        ]);
        if (cancelled) return;
        setEntries(list);
        setSummary(totals);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erro ao carregar finanças");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    setLoading(true);
    void load();
    return () => {
      cancelled = true;
    };
  }, [month, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { entries, summary, loading, error, refresh };
};
