"use client";

import { useEffect, type ReactNode } from "react";
import { hydrateValuesHidden, useValuesHidden } from "@/lib/privacy";

/**
 * Remounts the page when the eye is toggled.
 *
 * Money is formatted by plain functions that read the privacy flag, and a
 * page only re-renders when its own state changes — so the cheapest correct
 * way to repaint every figure (charts included) is a new `key`. Local UI
 * state resets on toggle; it is a rare action, and nothing is lost that a
 * tap cannot bring back.
 */
export const ValuesShell = ({ children }: { children: ReactNode }) => {
  const hidden = useValuesHidden();

  // Deferred a tick, like the bell's first load: the saved choice is applied
  // after hydration so server and client HTML agree.
  useEffect(() => {
    const timer = setTimeout(hydrateValuesHidden, 0);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div key={hidden ? "hidden" : "shown"} className="max-w-[1400px]">
      {children}
    </div>
  );
};
