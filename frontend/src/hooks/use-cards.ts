"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchCards, type CreditCard } from "@/lib/api";

/**
 * Every card with its computed invoices. `cards` stays null until the first
 * load resolves (or fails), so screens can tell "loading" from "no cards".
 */
export const useCards = () => {
  const [cards, setCards] = useState<CreditCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await fetchCards();
        if (cancelled) return;
        setCards(list);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erro ao carregar cartões");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { cards, error, refresh };
};
