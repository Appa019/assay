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

/** All four fit the tab bar, so nothing is folded away. */
export const PRIMARY_NAV = NAV_ITEMS;
export const SECONDARY_NAV: readonly NavItem[] = [];

export const isCurrentPath = (pathname: string, href: string): boolean =>
  href === "/" ? pathname === "/" : pathname.startsWith(href);
