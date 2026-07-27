"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  PlusCircle,
  Briefcase,
  FileBarChart,
  Settings,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Painel", icon: LayoutDashboard },
  { href: "/aporte", label: "Novo aporte", icon: PlusCircle },
  { href: "/ativos", label: "Carteira", icon: Briefcase },
  { href: "/relatorios", label: "Histórico", icon: FileBarChart },
  { href: "/configuracoes", label: "Ajustes", icon: Settings },
] as const;

export const Sidebar = () => {
  const pathname = usePathname();

  return (
    <aside
      className="w-60 border-r shrink-0 px-6 py-10 flex flex-col"
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
          Mesa de aportes
        </h1>
        <p
          className="text-[11px] mt-1.5 uppercase tracking-[0.18em]"
          style={{ color: "var(--text-muted)" }}
        >
          Aporte ad-hoc · comitê autônomo
        </p>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
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

      <div
        className="mt-auto pt-5 text-[11px] leading-relaxed"
        style={{ borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}
      >
        100% local · SQLite · Sem credenciais
      </div>
    </aside>
  );
};
