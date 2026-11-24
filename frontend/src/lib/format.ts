// Display helpers for the observability drawer.
import type { LLMUsage, Span } from "./events";

export function formatUsd(n: number): string {
  return n > 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export interface SpanNode {
  span: Span;
  children: SpanNode[];
}

/** Nest spans by parent_id; siblings in start order. Spans whose parent is missing become roots. */
export function buildSpanTree(spans: Span[]): SpanNode[] {
  const nodes = new Map(spans.map((s) => [s.span_id, { span: s, children: [] as SpanNode[] }]));
  const roots: SpanNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.span.parent_id ? nodes.get(node.span.parent_id) : undefined;
    (parent ? parent.children : roots).push(node);
  }
  const sort = (list: SpanNode[]) => {
    list.sort((a, b) => a.span.start_ms - b.span.start_ms);
    list.forEach((n) => sort(n.children));
  };
  sort(roots);
  return roots;
}

export function sumTokens(calls: Pick<LLMUsage, "input_tokens" | "output_tokens">[]): { input: number; output: number } {
  return calls.reduce(
    (acc, c) => ({ input: acc.input + (c.input_tokens ?? 0), output: acc.output + (c.output_tokens ?? 0) }),
    { input: 0, output: 0 },
  );
}
