"use client";

import { useState } from "react";
import { setChaos } from "@/lib/api";
import type { ChaosState } from "@/lib/events";

const TOOLS = [
  ["verify_customer", "Verify customer"],
  ["search_policies", "Search knowledge base"],
  ["list_invoices", "Find invoices"],
  ["issue_refund", "Issue refund"],
  ["update_account_field", "Update account"],
] as const;

/** Failure simulation for the demo. Flags apply to this conversation only; one-shot flags clear once used. */
export function ChaosMenu({ sessionId, chaos }: { sessionId: string | null; chaos: ChaosState }) {
  const [local, setLocal] = useState<ChaosState | null>(null);
  const [saving, setSaving] = useState(false);
  const state = local ?? chaos;

  async function update(patch: Partial<ChaosState>) {
    if (!sessionId) return;
    const next = { ...state, ...patch };
    setLocal(next);
    setSaving(true);
    try {
      setLocal(await setChaos(sessionId, next));
    } finally {
      setSaving(false);
      setLocal(null); // the next session refresh is the source of truth
    }
  }

  const check = (key: "llm_timeout_next" | "llm_429_next" | "llm_outage_next", label: string, hint: string) => (
    <label className="flex items-start gap-2 py-1 text-sm">
      <input
        type="checkbox"
        className="mt-1 accent-storm"
        checked={Boolean(state[key])}
        onChange={(e) => void update({ [key]: e.target.checked })}
      />
      <span>
        {label}
        <span className="block text-xs text-ink-soft">{hint}</span>
      </span>
    </label>
  );

  return (
    <details className="border-b border-line px-4 py-3">
      <summary className="cursor-pointer text-sm font-semibold">
        Simulate failures {saving && <span className="font-normal text-ink-soft">(saving)</span>}
      </summary>
      <div className="mt-2 space-y-1">
        {check("llm_timeout_next", "Next model call times out", "The backup model answers instead.")}
        {check("llm_429_next", "Next model call is rate-limited", "The assistant retries after a short wait.")}
        {check("llm_outage_next", "Next model call fails completely", "You get an error with a Retry button.")}
        <label className="flex items-center gap-2 py-1 text-sm">
          <span className="w-28 shrink-0">Next call fails</span>
          <select
            className="min-w-0 flex-1 rounded border border-line bg-surface px-1 py-0.5 text-sm"
            value={state.tool_fail_next ?? ""}
            onChange={(e) => void update({ tool_fail_next: e.target.value || null })}
          >
            <option value="">No tool</option>
            {TOOLS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 py-1 text-sm">
          <span className="w-28 shrink-0">Slow (+5 s)</span>
          <select
            className="min-w-0 flex-1 rounded border border-line bg-surface px-1 py-0.5 text-sm"
            value={state.tool_slow ?? ""}
            onChange={(e) => void update({ tool_slow: e.target.value || null })}
          >
            <option value="">No tool</option>
            {TOOLS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <p className="pt-1 text-xs text-ink-soft">
          Customer C-1006 always has a failing invoice system, to show repeated failures ending in a ticket.
        </p>
      </div>
    </details>
  );
}
