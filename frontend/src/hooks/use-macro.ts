"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchMacro, type MacroSnapshot } from "@/lib/api";

export const useMacro = () => {
  const [data, setData] = useState<MacroSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchMacro());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar macro");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
};
