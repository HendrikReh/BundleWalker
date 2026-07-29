// Copyright (C) 2026 Hendrik Reh
// SPDX-License-Identifier: GPL-3.0-or-later

import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router";
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
  title,
}: ComponentPropsWithoutRef<"a"> & {
  readonly children?: ReactNode;
  readonly node?: unknown;
}) {
  const link =
    href === undefined ? { kind: "unsafe" as const } : classifyLink(href);
  if (link.kind === "unsafe") {
    return <span>{children}</span>;
  }
  if (link.kind === "external") {
    return (
      <a
        href={link.href}
        title={title}
        target="_blank"
        rel="noopener noreferrer"
      >
        {children} <span className="external-label">(external)</span>
      </a>
    );
  }
  if (link.kind === "concept") {
    return (
      <Link to={link.href} title={title}>
        {children}
      </Link>
    );
  }
  return (
    <a href={link.href} title={title}>
      {children}
    </a>
  );
}

type ClassifiedLink =
  | { readonly kind: "unsafe" }
  | { readonly kind: "external"; readonly href: string }
  | { readonly kind: "concept"; readonly href: string }
  | { readonly kind: "local"; readonly href: string };

function classifyLink(href: string): ClassifiedLink {
  if (
    href.length === 0 ||
    href.includes("\\") ||
    /[\u0000-\u001f\u007f]/u.test(href)
  ) {
    return { kind: "unsafe" };
  }
  if (href.startsWith("//")) {
    return isHttpUrl(`https:${href}`)
      ? { kind: "external", href }
      : { kind: "unsafe" };
  }
  if (/^[A-Za-z][A-Za-z0-9+.-]*:/u.test(href)) {
    return isHttpUrl(href) ? { kind: "external", href } : { kind: "unsafe" };
  }
  if (href.startsWith("#")) return { kind: "local", href };

  const suffixStart = href.search(/[?#]/u);
  const rawPath = suffixStart === -1 ? href : href.slice(0, suffixStart);
  const suffix = suffixStart === -1 ? "" : href.slice(suffixStart);
  const rooted = rawPath.startsWith("/");
  const pathWithoutRoot = rooted ? rawPath.slice(1) : rawPath;
  const rawSegments = pathWithoutRoot.split("/");
  if (
    rawPath.startsWith("//") ||
    rawSegments.some((segment) => segment.length === 0)
  ) {
    return rawPath === "/" ? { kind: "local", href } : { kind: "unsafe" };
  }

  const segments: string[] = [];
  try {
    for (const segment of rawSegments) {
      const decoded = decodeURIComponent(segment);
      if (
        decoded === "." ||
        decoded === ".." ||
        decoded.includes("/") ||
        decoded.includes("\\") ||
        /[\u0000-\u001f\u007f]/u.test(decoded)
      ) {
        return { kind: "unsafe" };
      }
      segments.push(decoded);
    }
  } catch {
    return { kind: "unsafe" };
  }

  const lastSegment = segments.at(-1);
  if (lastSegment?.endsWith(".md")) {
    const conceptSegments = [
      ...segments.slice(0, -1),
      lastSegment.slice(0, -".md".length),
    ];
    if (conceptSegments.some((segment) => segment.length === 0)) {
      return { kind: "unsafe" };
    }
    return {
      kind: "concept",
      href: `/browse/${conceptSegments.map(encodeURIComponent).join("/")}${suffix}`,
    };
  }
  return { kind: "local", href };
}

function isHttpUrl(href: string): boolean {
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}
