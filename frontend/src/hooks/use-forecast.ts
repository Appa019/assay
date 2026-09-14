"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchForecast, type Forecast } from "@/lib/api";

/**
 * Committed money in and out for the months ahead. `forecast` stays null
 * until the first load resolves, so the screen can tell "loading" from
 * "nothing registered yet" — two states that must not look alike here.
 */
export const useForecast = (months = 6) => {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchForecast(months);
        if (cancelled) return;
        setForecast(data);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erro ao carregar o fluxo");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [months, version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { forecast, error, loading, refresh };
};
