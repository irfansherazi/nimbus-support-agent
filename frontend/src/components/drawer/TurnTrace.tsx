import { formatMs, formatUsd, sumTokens } from "@/lib/format";
import type { TurnView } from "@/lib/session-store";
import { SpanTree } from "./SpanTree";

const STATUS: Record<TurnView["status"], string> = {
  running: "Running",
  ok: "Answered",
  escalated: "Escalated",
  failed: "Failed",
};

export function TurnTrace({ turn, index }: { turn: TurnView; index: number }) {
  const latency = turn.usage?.latency;
  const tokens = sumTokens(turn.usage?.calls ?? []);
  return (
    <section className="border-b border-line px-4 py-3">
      <header className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">Turn {index + 1}</h3>
        <span className="text-xs text-ink-soft">
          {turn.channel === "voice" ? "Voice" : "Chat"}, {STATUS[turn.status]}
        </span>
      </header>
      {turn.userText && <p className="mt-1 line-clamp-2 text-xs text-ink-soft">“{turn.userText}”</p>}

      <dl className="tabular mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-ink-soft">End to end</dt>
        <dd className="text-right">{formatMs(latency?.total_ms)}</dd>
        {turn.channel === "voice" ? (
          <>
            <dt className="text-ink-soft">Speech end to first audio</dt>
            <dd className="text-right">{formatMs(latency?.voice_e2e_ms)}</dd>
          </>
        ) : (
          <>
            <dt className="text-ink-soft">First token</dt>
            <dd className="text-right">{formatMs(latency?.ttft_ms)}</dd>
          </>
        )}
        <dt className="text-ink-soft">Tokens in / out</dt>
        <dd className="text-right">
          {tokens.input.toLocaleString()} / {tokens.output.toLocaleString()}
        </dd>
        <dt className="text-ink-soft">Model calls</dt>
        <dd className="text-right">{turn.usage?.calls.length ?? 0}</dd>
        <dt className="text-ink-soft">Estimated cost</dt>
        <dd className="text-right">{formatUsd(turn.usage?.turn_cost_usd ?? 0)}</dd>
      </dl>

      {turn.trace && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-storm">Trace ({turn.trace.length} spans)</summary>
          <div className="mt-1">
            <SpanTree spans={turn.trace} />
          </div>
        </details>
      )}
    </section>
  );
}
