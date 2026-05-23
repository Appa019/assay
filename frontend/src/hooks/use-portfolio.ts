"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchPortfolio, type PortfolioSummary } from "@/lib/api";

export const usePortfolio = () => {
  const [data, setData] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await fetchPortfolio();
      setData(summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar carteira");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
};
