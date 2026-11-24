import type { Span } from "@/lib/events";
import { buildSpanTree, formatMs, formatUsd, type SpanNode } from "@/lib/format";

const KIND_COLOR: Record<Span["kind"], string> = {
  node: "text-ink-soft",
  llm: "text-storm",
  tool: "text-rain",
  retrieval: "text-rain",
  guardrail: "text-amber",
  voice: "text-storm",
};

function Json({ value }: { value: unknown }) {
  return (
    <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded bg-cloud p-2 text-[11px] leading-4 text-ink">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Detail({ span }: { span: Span }) {
  const a = span.attrs as Record<string, unknown>;
  if (span.kind === "llm") {
    return (
      <div className="space-y-1 text-xs text-ink-soft">
        <p className="tabular">
          {String(a.model)} for {String(a.purpose)}, {String(a.input_tokens)} in / {String(a.output_tokens)} out,{" "}
          {formatUsd(Number(a.cost_usd ?? 0))}
        </p>
        <details>
          <summary className="cursor-pointer text-storm">Prompt</summary>
          <Json value={a.prompt} />
        </details>
        <details>
          <summary className="cursor-pointer text-storm">Output</summary>
          <Json value={a.output} />
        </details>
      </div>
    );
  }
  if (span.kind === "tool") {
    return (
      <details className="text-xs">
        <summary className="cursor-pointer text-storm">Arguments and result</summary>
        <Json value={{ args: a.args, result: a.result }} />
      </details>
    );
  }
  return Object.keys(a).length ? <Json value={a} /> : null;
}

function NodeRow({ node, depth }: { node: SpanNode; depth: number }) {
  const s = node.span;
  const failed = "error" in s.attrs || s.attrs.ok === false;
  const drift = s.name === "voice_drift" && s.attrs.drift === true;
  return (
    <li>
      <details open={depth === 0 && s.kind === "node" ? undefined : false} className="group">
        <summary
          className="flex cursor-pointer items-baseline gap-2 py-0.5 text-[13px]"
          style={{ paddingLeft: depth * 14 }}
        >
          <span className={`${KIND_COLOR[s.kind]} ${failed || drift ? "!text-ember" : ""}`}>{s.name}</span>
          <span className="tabular ml-auto text-xs text-ink-soft">{formatMs(s.duration_ms)}</span>
        </summary>
        <div style={{ paddingLeft: depth * 14 + 8 }} className="pb-1">
          <Detail span={s} />
        </div>
      </details>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((c) => (
            <NodeRow key={c.span.span_id} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function SpanTree({ spans }: { spans: Span[] }) {
  const roots = buildSpanTree(spans);
  if (roots.length === 0) return <p className="text-xs text-ink-soft">No trace recorded.</p>;
  return (
    <ul aria-label="Trace spans">
      {roots.map((n) => (
        <NodeRow key={n.span.span_id} node={n} depth={0} />
      ))}
    </ul>
  );
}
