"use client";

import { Download } from "lucide-react";

/** Slug safe for a filename on iOS, macOS and Linux alike. */
const toFilename = (title: string): string => {
  const slug = title
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "relatorio"}.md`;
};

/**
 * Saves the document the user is reading. Built client-side from text already
 * loaded, so it costs no round trip; on iOS the blob lands in Files, from where
 * it can be shared or opened in any editor.
 */
export const DownloadButton = ({
  content,
  title,
  label = "Baixar",
}: {
  content: string;
  title: string;
  label?: string;
}) => {
  const download = () => {
    const blob = new Blob([`# ${title}\n\n${content}`], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = toFilename(title);
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoking immediately can cancel the download in Safari; a task later is
    // enough to keep the reference alive through the click.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <button
      type="button"
      onClick={download}
      className="flex min-h-[2.75rem] shrink-0 items-center gap-2 rounded-md border px-3.5 text-[13px] font-medium md:min-h-0 md:py-2"
      style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
    >
      <Download size={14} strokeWidth={1.9} />
      {label}
    </button>
  );
};
