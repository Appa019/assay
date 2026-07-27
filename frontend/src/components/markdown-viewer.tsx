"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import GithubSlugger from "github-slugger";
import { TableOfContents } from "lucide-react";

type TocEntry = {
  id: string;
  text: string;
  level: number;
};

/** Strip inline markdown so the slug matches what rehype-slug computes. */
const plainHeadingText = (raw: string): string =>
  raw
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .trim();

/**
 * Build the TOC from raw markdown. Every heading level feeds the slugger so
 * duplicate-suffix counters stay in sync with rehype-slug, but only levels
 * 1-3 are listed.
 */
const extractToc = (content: string): TocEntry[] => {
  const slugger = new GithubSlugger();
  const entries: TocEntry[] = [];
  let inFence = false;

  for (const line of content.split("\n")) {
    const trimmed = line.trimStart();
    if (/^(```|~~~)/.test(trimmed)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(trimmed);
    if (!match) continue;
    const level = match[1].length;
    const text = plainHeadingText(match[2]);
    if (!text) continue;
    const id = slugger.slug(text);
    if (level <= 3) entries.push({ id, text, level });
  }
  return entries;
};

const TocNav = ({
  entries,
  activeId,
  onNavigate,
}: {
  entries: TocEntry[];
  activeId: string | null;
  onNavigate: (id: string) => void;
}) => (
  <nav aria-label="Índice do documento" className="text-xs">
    <p
      className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.16em] font-medium mb-3"
      style={{ color: "var(--text-muted)" }}
    >
      <TableOfContents size={12} />
      Índice
    </p>
    <ul className="space-y-1">
      {entries.map((entry) => (
        <li key={entry.id}>
          <button
            type="button"
            onClick={() => onNavigate(entry.id)}
            className="block w-full text-left leading-snug py-1 rounded-sm transition-colors"
            style={{
              paddingLeft: (entry.level - 1) * 12,
              color:
                activeId === entry.id
                  ? "var(--accent-strong)"
                  : "var(--text-secondary)",
              fontWeight: activeId === entry.id ? 600 : 400,
            }}
          >
            {entry.text}
          </button>
        </li>
      ))}
    </ul>
  </nav>
);

export const MarkdownViewer = ({
  content,
  withToc = true,
  maxHeight,
}: {
  content: string;
  withToc?: boolean;
  /** Cap the document area with its own scrollbar (long docs inside cards). */
  maxHeight?: number;
}) => {
  const toc = useMemo(() => extractToc(content), [content]);
  const showToc = withToc && toc.length >= 3;
  const [activeId, setActiveId] = useState<string | null>(null);
  const articleRef = useRef<HTMLDivElement>(null);

  // Scroll-spy: highlight the TOC entry whose heading is closest to the top.
  useEffect(() => {
    if (!showToc || !articleRef.current) return;
    const headings = Array.from(
      articleRef.current.querySelectorAll<HTMLElement>("h1[id], h2[id], h3[id]")
    );
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (observed) => {
        const visible = observed
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActiveId(visible[0].target.id);
      },
      { rootMargin: "0px 0px -70% 0px" }
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [showToc, content]);

  const handleNavigate = (id: string) => {
    setActiveId(id);
    articleRef.current
      ?.querySelector(`[id="${CSS.escape(id)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const article = (
    <div
      ref={articleRef}
      className="md-doc min-w-0 flex-1"
      style={
        maxHeight !== undefined
          ? { maxHeight, overflowY: "auto", paddingRight: 12 }
          : undefined
      }
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug]}
        components={{
          // Wrap tables so wide committee matrices scroll inside their own box.
          table: ({ children }) => (
            <div className="md-table-wrap">
              <table>{children}</table>
            </div>
          ),
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );

  if (!showToc) return article;

  return (
    <div className="flex gap-8 items-start">
      {article}
      <aside
        className="hidden lg:block w-52 shrink-0 sticky top-6 max-h-[80vh] overflow-y-auto pl-4"
        style={{ borderLeft: "1px solid var(--border)" }}
      >
        <TocNav entries={toc} activeId={activeId} onNavigate={handleNavigate} />
      </aside>
    </div>
  );
};
