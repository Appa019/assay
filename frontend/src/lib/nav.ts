import {
  LayoutDashboard,
  MessagesSquare,
  Receipt,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  /** Shortened for the bottom tab bar, where horizontal room is scarce. */
  shortLabel: string;
  icon: LucideIcon;
};

/**
 * Four destinations, one job each.
 *
 * Nothing here takes an entry: expenses and income are logged by talking to
 * the consultant, and Extrato only reads them back. The portfolio,
 * contributions, committee history and tax view are sections of Investimentos.
 * Fewer, fatter tabs beat eight thin ones on a phone.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "Visão geral", shortLabel: "Visão geral", icon: LayoutDashboard },
  { href: "/consultor", label: "Consultor", shortLabel: "Consultor", icon: MessagesSquare },
  { href: "/extrato", label: "Extrato", shortLabel: "Extrato", icon: Receipt },
  { href: "/investimentos", label: "Investimentos", shortLabel: "Investir", icon: TrendingUp },
] as const;

// Legacy routes still served for deep links, owned by an Investimentos tab.
const INVESTMENT_ROUTES = ["/aporte", "/relatorios", "/ativos", "/ir"];

export const isCurrentPath = (pathname: string, href: string): boolean => {
  if (href === "/") return pathname === "/";
  if (href === "/investimentos" && INVESTMENT_ROUTES.some((r) => pathname.startsWith(r))) {
    return true;
  }
  return pathname.startsWith(href);
};
