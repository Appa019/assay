import { useSyncExternalStore } from "react";

/**
 * "Hide values" switch. A tiny external store so the money formatters (plain
 * functions) can read it synchronously, plus a hook for the toggle button.
 *
 * The flag starts as `false` on server and client alike: reading localStorage
 * during render would make the hydrated HTML disagree with the server's.
 * `hydrateValuesHidden()` applies the saved choice after mount instead.
 */

const STORAGE_KEY = "assay.values-hidden";
const listeners = new Set<() => void>();
let hidden = false;

const notifyAll = () => {
  for (const notify of listeners) notify();
};

export const valuesHidden = (): boolean => hidden;

export const setValuesHidden = (next: boolean): void => {
  if (next === hidden) return;
  hidden = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // Private mode or blocked storage: the choice lives for this page only.
  }
  notifyAll();
};

export const toggleValuesHidden = (): void => setValuesHidden(!hidden);

/** Apply the saved choice. Call once after mount, never during render. */
export const hydrateValuesHidden = (): void => {
  try {
    if (window.localStorage.getItem(STORAGE_KEY) === "1") setValuesHidden(true);
  } catch {
    // No storage: stay visible.
  }
};

const subscribe = (notify: () => void) => {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
};
const getSnapshot = () => hidden;
const getServerSnapshot = () => false;

export const useValuesHidden = (): boolean =>
  useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
