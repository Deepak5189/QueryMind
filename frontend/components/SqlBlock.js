"use client";

import { useState } from "react";

export default function SqlBlock({ sql, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);

  if (!sql) return null;

  async function handleCopy(e) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable -- fail silently, copy just won't work
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-ink-600 bg-ink-900/60">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 font-mono text-xs uppercase tracking-wide text-ledger-gold">
          <span className={`transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
          Generated SQL
        </span>
        <span
          onClick={handleCopy}
          role="button"
          tabIndex={0}
          className="rounded border border-ink-600 px-2 py-0.5 text-[11px] text-parchment-300/70 hover:border-ledger-gold hover:text-ledger-gold"
        >
          {copied ? "Copied" : "Copy"}
        </span>
      </button>
      {open && (
        <pre className="overflow-x-auto border-t border-ink-600 px-3 py-3 font-mono text-[13px] leading-relaxed text-parchment-100">
          {sql}
        </pre>
      )}
    </div>
  );
}
