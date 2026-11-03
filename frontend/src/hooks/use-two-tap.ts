"use client";

import { useEffect, useState } from "react";

/**
 * Destructive buttons take two taps on the same button: the first arms it
 * (the caller shows "toque de novo"), the second runs the action. iOS renders
 * window.confirm as a system alert, so this replaces it. Disarms after 4 s.
 */
export const useTwoTap = () => {
  const [armed, setArmed] = useState<string | null>(null);

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(null), 4000);
    return () => clearTimeout(timer);
  }, [armed]);

  const tap = (key: string, action: () => void) => {
    if (armed !== key) {
      setArmed(key);
      return;
    }
    setArmed(null);
    action();
  };

  return { armed, tap };
};
