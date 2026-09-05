"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, isCurrentPath } from "@/lib/nav";
import { NotificationsBell } from "@/components/notifications-bell";

/** Desktop navigation. Below `md` the bottom tab bar replaces it entirely. */
export const Sidebar = () => {
  const pathname = usePathname();

  return (
    <aside
      className="hidden md:flex w-60 border-r shrink-0 px-6 py-10 flex-col"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="mb-12">
        <h1
          className="text-2xl tracking-tight leading-none"
          style={{
            fontFamily: "var(--font-heading)",
            color: "var(--text-primary)",
          }}
        >
          Assay
        </h1>
        <p
          className="text-[11px] mt-1.5 uppercase tracking-[0.18em]"
          style={{ color: "var(--text-muted)" }}
        >
          Finanças · investimentos
        </p>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive = isCurrentPath(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={isActive ? "page" : undefined}
              className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
              style={
                {
                  background: isActive ? "var(--accent-light)" : "transparent",
                  color: isActive ? "var(--accent)" : "var(--text-secondary)",
                  "--tw-ring-color": "var(--accent)",
                  "--tw-ring-offset-color": "var(--bg-primary)",
                } as React.CSSProperties
              }
            >
              <Icon size={17} strokeWidth={1.8} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Pushed to the bottom: it is a place to check, not a destination. */}
      <div className="mt-auto pt-8">
        <NotificationsBell variant="sidebar" />
      </div>
    </aside>
  );
};
