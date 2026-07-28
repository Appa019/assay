import {
  LayoutDashboard,
  MessagesSquare,
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
 * Three destinations, one job each.
 *
 * Everything that used to be its own tab now lives inside one of these:
 * expenses and income are logged by talking to the consultant, and the
 * portfolio, contributions, committee history and tax view are sections of
 * Investimentos. Fewer, fatter tabs beat eight thin ones on a phone.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", label: "Visão geral", shortLabel: "Visão geral", icon: LayoutDashboard },
  { href: "/consultor", label: "Consultor", shortLabel: "Consultor", icon: MessagesSquare },
  { href: "/investimentos", label: "Investimentos", shortLabel: "Investir", icon: TrendingUp },
] as const;

/** All three fit the tab bar, so nothing is folded away. */
export const PRIMARY_NAV = NAV_ITEMS;
export const SECONDARY_NAV: readonly NavItem[] = [];

export const isCurrentPath = (pathname: string, href: string): boolean =>
  href === "/" ? pathname === "/" : pathname.startsWith(href);
