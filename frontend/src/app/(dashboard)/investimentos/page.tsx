"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { AtivosView } from "@/app/(dashboard)/ativos/page";
import { AporteView } from "@/app/(dashboard)/aporte/page";
import { RelatoriosView } from "@/app/(dashboard)/relatorios/page";
import { IrView } from "@/app/(dashboard)/ir/page";

type TabKey = "carteira" | "aportar" | "analises" | "ir";

type Tab = {
  key: TabKey;
  /** Kept short so all four segments fit a 390px screen without scrolling. */
  label: string;
  /** Read out after the label; the terse labels are ambiguous out of context. */
  hint: string;
};

const TABS: readonly Tab[] = [
  { key: "carteira", label: "Carteira", hint: "posições e operações" },
  { key: "aportar", label: "Aportar", hint: "novo aporte" },
  { key: "analises", label: "Análises", hint: "relatórios do comitê" },
  { key: "ir", label: "IR", hint: "imposto de renda" },
] as const;

const DEFAULT_TAB: TabKey = "carteira";

const isTabKey = (value: string | null): value is TabKey =>
  TABS.some((tab) => tab.key === value);

/** Masthead. Deliberately eyebrow-sized: the page title belongs to the section
 *  below, so two serif headings never stack on a phone. */
const Masthead = () => (
  <p
    className="text-[11px] font-medium uppercase tracking-[0.18em]"
    style={{ color: "var(--text-muted)" }}
  >
    Mesa · investimentos
  </p>
);

const TabRail = ({
  active,
  onSelect,
}: {
  active: TabKey;
  onSelect: (key: TabKey) => void;
}) => (
  <nav
    aria-label="Seções de investimentos"
    // Four equal segments under the thumb; on a wide screen they collapse to
    // their label width and sit left-aligned on the rule, like a masthead.
    className="flex md:gap-9"
    style={{ borderBottom: "1px solid var(--border)" }}
  >
    {TABS.map((tab) => {
      const selected = tab.key === active;
      return (
        <button
          key={tab.key}
          type="button"
          onClick={() => onSelect(tab.key)}
          aria-current={selected ? "page" : undefined}
          className="relative flex min-h-12 flex-1 items-center justify-center px-1 text-[13px] font-semibold transition-colors md:flex-none md:justify-start md:px-0 md:text-sm"
          style={{
            color: selected ? "var(--text-primary)" : "var(--text-muted)",
          }}
        >
          {tab.label}
          {/* Appended rather than an aria-label so the accessible name still
              starts with the text on screen. */}
          <span className="sr-only"> — {tab.hint}</span>
          {selected && (
            /* Ink bar slides between segments — the only motion in the shell. */
            <motion.span
              layoutId="aba-ativa"
              aria-hidden
              className="absolute inset-x-0 -bottom-px h-[2px]"
              style={{ background: "var(--accent)" }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            />
          )}
        </button>
      );
    })}
  </nav>
);

const ActivePanel = ({ tab }: { tab: TabKey }) => {
  if (tab === "aportar") return <AporteView />;
  if (tab === "analises") return <RelatoriosView />;
  if (tab === "ir") return <IrView />;
  return <AtivosView />;
};

const InvestimentosShell = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  // The URL is the single source of truth: a reload or a shared link lands on
  // the same section, and there is no state to keep in sync with it.
  const requested = searchParams.get("aba");
  const active: TabKey = isTabKey(requested) ? requested : DEFAULT_TAB;

  const handleSelect = (key: TabKey) => {
    if (key === active) return;
    // `replace` keeps the back button pointing at the previous page rather than
    // walking back through every section the thumb passed over.
    router.replace(`/investimentos?aba=${key}`, { scroll: false });
  };

  return (
    <div className="max-w-6xl">
      <Masthead />
      <div className="mt-4 md:mt-5">
        <TabRail active={active} onSelect={handleSelect} />
      </div>
      <motion.div
        key={active}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18, ease: "easeOut" }}
        className="mt-8 min-w-0 md:mt-11"
      >
        <ActivePanel tab={active} />
      </motion.div>
    </div>
  );
};

/** Rendered while the router resolves the query string on first paint. */
const ShellSkeleton = () => (
  <div className="max-w-6xl">
    <Masthead />
    <div
      className="mt-4 h-12 md:mt-5"
      style={{ borderBottom: "1px solid var(--border)" }}
    />
    <div
      className="mt-8 h-64 animate-pulse rounded-md md:mt-11"
      style={{ background: "var(--bg-secondary)" }}
    />
  </div>
);

// `useSearchParams` forces a Suspense boundary in Next 16 or the build fails.
const InvestimentosPage = () => (
  <Suspense fallback={<ShellSkeleton />}>
    <InvestimentosShell />
  </Suspense>
);

export default InvestimentosPage;
