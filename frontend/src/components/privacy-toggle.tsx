"use client";

import { Eye, EyeOff } from "lucide-react";
import { toggleValuesHidden, useValuesHidden } from "@/lib/privacy";

/**
 * The eye. Rendered twice by the shell, like the bell: inline in the desktop
 * sidebar, floating beside the bell on phones.
 */
export const PrivacyToggle = ({ variant }: { variant: "sidebar" | "floating" }) => {
  const hidden = useValuesHidden();
  const Icon = hidden ? EyeOff : Eye;
  const label = hidden ? "Mostrar valores" : "Ocultar valores";
  return (
    <button
      type="button"
      onClick={toggleValuesHidden}
      aria-label={label}
      aria-pressed={hidden}
      className={
        variant === "sidebar"
          ? "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium w-full"
          : "md:hidden fixed right-[4.25rem] z-40 flex items-center justify-center h-11 w-11 rounded-full"
      }
      style={
        variant === "sidebar"
          ? { color: "var(--text-secondary)" }
          : {
              top: "calc(env(safe-area-inset-top) + 0.75rem)",
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
            }
      }
    >
      <Icon size={17} strokeWidth={1.8} />
      {variant === "sidebar" && label}
    </button>
  );
};
