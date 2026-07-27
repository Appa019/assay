"use client";

import { useEffect, useState } from "react";
import { fetchPortfolioHistory, type PortfolioHistoryPoint } from "@/lib/api";

/**
 * Equity-curve snapshots. `data` stays null when the endpoint is missing
 * (404), empty or unreachable — callers hide the section gracefully.
 */
export const usePortfolioHistory = (days = 365) => {
  const [data, setData] = useState<PortfolioHistoryPoint[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const points = await fetchPortfolioHistory(days);
        if (!cancelled) setData(points && points.length > 0 ? points : null);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [days]);

  return { data, loading };
};
