"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchCadence, type CadenceStatus } from "@/lib/api";

export const useCadence = () => {
  const [data, setData] = useState<CadenceStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchCadence());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh };
};
