"use client";

import type { VoiceState, VoiceStatus } from "@/lib/voice/voice-state";
import { Waveform } from "./Waveform";

const STATUS: Record<VoiceStatus, string> = {
  idle: "",
  connecting: "Connecting…",
  listening: "Listening",
  user_speaking: "Hearing you…",
  thinking: "Checking…",
  agent_speaking: "Speaking. Talk any time to interrupt.",
  ended: "Call ended",
  error: "Voice unavailable",
};

export function MicButton({ live, disabled, onStart }: { live: boolean; disabled: boolean; onStart: () => void }) {
  if (live) return null;
  return (
    <button
      type="button"
      onClick={onStart}
      disabled={disabled}
      aria-label="Start a voice call"
      title="Talk instead of typing"
      className="flex h-10 w-10 items-center justify-center rounded-xl border border-line text-storm hover:border-storm/50 disabled:opacity-40"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
      </svg>
    </button>
  );
}

/** Shown above the composer while a call is live, or briefly after it ends with a reason. */
export function VoicePanel({
  state,
  live,
  micBars,
  agentBars,
  onEnd,
  onDismiss,
}: {
  state: VoiceState;
  live: boolean;
  micBars: () => number[];
  agentBars: () => number[];
  onEnd: () => void;
  onDismiss: () => void;
}) {
  if (!live) {
    if ((state.status === "ended" || state.status === "error") && state.message) {
      return (
        <div role="status" className="flex items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2 text-sm">
          <p className={`flex-1 ${state.status === "error" ? "text-ember" : "text-ink-soft"}`}>{state.message}</p>
          <button type="button" onClick={onDismiss} className="text-ink-soft hover:text-ink">
            Dismiss
          </button>
        </div>
      );
    }
    return null;
  }
  return (
    <section aria-label="Voice call" className="rounded-xl border border-storm/30 bg-surface px-3 py-2">
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${state.status === "connecting" ? "bg-amber" : "node-running bg-rain"}`}
        />
        <p className="flex-1 text-sm" aria-live="polite">
          {STATUS[state.status]}
        </p>
        <button type="button" onClick={onEnd} className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-white">
          End call
        </button>
      </div>
      <div className="mt-2 flex flex-col gap-1 sm:flex-row sm:gap-4">
        <Waveform bars={micBars} color="#34407a" label="You" />
        <Waveform bars={agentBars} color="#138a8a" label="Nimbus" />
      </div>
      {state.partialUser && <p className="mt-1 truncate text-sm italic text-ink-soft">{state.partialUser}</p>}
    </section>
  );
}
