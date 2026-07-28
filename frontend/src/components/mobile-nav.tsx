"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, isCurrentPath } from "@/lib/nav";

/**
 * Bottom tab bar for the phone, hidden from `md` up where the sidebar takes
 * over. Three destinations, so every one gets a comfortable thumb target and
 * nothing hides behind an overflow menu.
 */
export const MobileNav = () => {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Navegação principal"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t md:hidden"
      style={{
        background: "var(--bg-card)",
        borderColor: "var(--border)",
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
    >
      {NAV_ITEMS.map(({ href, shortLabel, icon: Icon }) => {
        const active = isCurrentPath(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className="relative flex min-h-[3.4rem] flex-col items-center justify-center gap-1 pt-2 pb-1"
            style={{ color: active ? "var(--accent-strong)" : "var(--text-muted)" }}
          >
            {active && (
              <span
                aria-hidden
                className="absolute top-0 h-0.5 w-10 rounded-full"
                style={{ background: "var(--accent)" }}
              />
            )}
            <Icon size={21} strokeWidth={active ? 2.2 : 1.7} />
            <span className="text-[11px] font-medium tracking-tight">{shortLabel}</span>
          </Link>
        );
      })}
    </nav>
  );
};
