// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownContent({ markdown }: { readonly markdown: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: SafeLink,
          h1: "h2",
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function SafeLink({
  href,
  children,
  ...properties
}: ComponentPropsWithoutRef<"a"> & { readonly children?: ReactNode }) {
  if (href === undefined || !isSafeHref(href)) {
    return <span>{children}</span>;
  }
  if (isExternalHref(href)) {
    return (
      <a {...properties} href={href} target="_blank" rel="noopener noreferrer">
        {children} <span className="external-label">(external)</span>
      </a>
    );
  }
  return (
    <a {...properties} href={href}>
      {children}
    </a>
  );
}

function isSafeHref(href: string): boolean {
  if (href.startsWith("/") || href.startsWith("#")) return true;
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function isExternalHref(href: string): boolean {
  return href.startsWith("http://") || href.startsWith("https://");
}
