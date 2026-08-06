/** Browser side of Web Push: register the service worker, subscribe this
 * device and keep the backend in sync. iOS quirk baked in: push only works
 * when the PWA was opened from the Home Screen (standalone), never in Safari
 * tabs — callers use `pushEnvironment()` to explain that instead of failing. */

import {
  deletePushSubscription,
  fetchVapidPublicKey,
  savePushSubscription,
} from "@/lib/api";

export type PushEnvironment = "ready" | "needs-install" | "unsupported";

const isStandalone = (): boolean =>
  window.matchMedia("(display-mode: standalone)").matches ||
  // iOS Safari exposes this non-standard flag on the installed web app.
  ("standalone" in navigator && (navigator as { standalone?: boolean }).standalone === true);

export const pushEnvironment = (): PushEnvironment => {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    // On iOS this is exactly what a Safari tab reports — installing fixes it.
    return isStandalone() ? "unsupported" : "needs-install";
  }
  return "ready";
};

const urlBase64ToUint8Array = (base64: string): Uint8Array => {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  return Uint8Array.from(raw, (ch) => ch.charCodeAt(0));
};

const registration = async (): Promise<ServiceWorkerRegistration> => {
  await navigator.serviceWorker.register("/sw.js");
  return navigator.serviceWorker.ready;
};

export const currentSubscription = async (): Promise<PushSubscription | null> => {
  if (pushEnvironment() !== "ready") return null;
  const reg = await registration();
  return reg.pushManager.getSubscription();
};

/** Ask permission (must run inside a user gesture) and register this device. */
export const enablePush = async (): Promise<void> => {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(
      permission === "denied"
        ? "Notificações bloqueadas. Libere em Ajustes > Notificações > Assay."
        : "Permissão não concedida.",
    );
  }
  const reg = await registration();
  const key = await fetchVapidPublicKey();
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key).buffer as ArrayBuffer,
    }));
  await savePushSubscription(subscription.toJSON());
};

export const disablePush = async (): Promise<void> => {
  const subscription = await currentSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  await deletePushSubscription(endpoint);
};
