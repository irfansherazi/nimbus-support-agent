import type { StreamStatus } from "@/lib/events";
import type { SessionState } from "@/lib/session-store";

const PLAN = { free: "Free", pro: "Pro", enterprise: "Enterprise" } as const;
const CONTRACT = { active: "active", expired: "expired", past_due: "past due" } as const;

export function StatusBar({
  state,
  stream,
  drawerOpen,
  onToggleDrawer,
  onNew,
}: {
  state: SessionState;
  stream: StreamStatus;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  onNew: () => void;
}) {
  const c = state.customer;
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-3 sm:px-6">
      <div className="flex items-center gap-2">
        <svg width="22" height="16" viewBox="0 0 22 16" aria-hidden className="text-storm">
          <path
            fill="currentColor"
            d="M17.5 6.1A6 6 0 0 0 6 4.6 4.6 4.6 0 0 0 5 13.7h12.3a3.9 3.9 0 0 0 .2-7.6Z"
          />
        </svg>
        <span className="text-[17px] font-semibold tracking-tight">Nimbus Support</span>
      </div>

      <div className="flex flex-1 flex-wrap items-center gap-2 text-sm">
        {c ? (
          <span className="rounded-full bg-rain-soft px-2.5 py-1 text-rain">
            Verified: {c.name}, {PLAN[c.tier]} plan ({CONTRACT[c.contract_status]})
          </span>
        ) : (
          <span className="rounded-full bg-cloud px-2.5 py-1 text-ink-soft">Not verified</span>
        )}
        {state.escalation && (
          <span className="rounded-full bg-storm-soft px-2.5 py-1 text-storm">
            Ticket {state.escalation.ticket_id} open with a specialist
          </span>
        )}
        {stream === "reconnecting" && <span className="text-amber">Reconnecting…</span>}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onNew}
          className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-storm/50"
        >
          New conversation
        </button>
        <button
          type="button"
          onClick={onToggleDrawer}
          aria-expanded={drawerOpen}
          aria-controls="observability"
          className="rounded-lg bg-storm-soft px-3 py-1.5 text-sm text-storm hover:bg-storm hover:text-white"
        >
          {drawerOpen ? "Hide agent trace" : "Show agent trace"}
        </button>
      </div>
    </header>
  );
}
