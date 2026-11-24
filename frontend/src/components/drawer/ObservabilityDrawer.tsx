"use client";

import { useEffect, useState } from "react";
import { getTickets } from "@/lib/api";
import type { Ticket } from "@/lib/events";
import { formatUsd } from "@/lib/format";
import type { SessionState } from "@/lib/session-store";
import { ChaosMenu } from "./ChaosMenu";
import { TurnTrace } from "./TurnTrace";

export function ObservabilityDrawer({ state, onClose }: { state: SessionState; onClose: () => void }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const ticketKey = state.escalation?.ticket_id ?? "";

  useEffect(() => {
    if (!state.sessionId) return;
    getTickets(state.sessionId)
      .then(setTickets)
      .catch(() => setTickets([]));
  }, [state.sessionId, ticketKey, state.turns.length]);

  const turns = state.turns.map((t, i) => ({ t, i })).reverse();

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-baseline gap-2 border-b border-line px-4 py-3">
        <h2 className="text-[15px] font-semibold">Agent trace</h2>
        <span className="tabular text-xs text-ink-soft">Session cost {formatUsd(state.usageTotal)}</span>
        <button type="button" onClick={onClose} className="ml-auto text-sm text-storm lg:hidden">
          Close
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <ChaosMenu sessionId={state.sessionId} chaos={state.chaos} />

        {tickets.length > 0 && (
          <details open className="border-b border-line px-4 py-3">
            <summary className="cursor-pointer text-sm font-semibold">Tickets ({tickets.length})</summary>
            <ul className="mt-2 space-y-2">
              {tickets.map((t) => (
                <li key={t.id} className="rounded-md bg-cloud p-2 text-xs">
                  <p className="font-semibold text-ink">
                    {t.id}, {t.category}, {t.priority} priority
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap text-ink-soft">{t.summary}</p>
                  <p className="mt-0.5 text-ink-soft">Reason: {t.reason.replaceAll("_", " ")}</p>
                </li>
              ))}
            </ul>
          </details>
        )}

        {turns.length === 0 ? (
          <p className="px-4 py-6 text-sm text-ink-soft">
            Each answer shows up here with its timing, tokens, cost and the full trace of model and tool calls.
          </p>
        ) : (
          turns.map(({ t, i }) => <TurnTrace key={t.turnId} turn={t} index={i} />)
        )}
      </div>
    </div>
  );
}
