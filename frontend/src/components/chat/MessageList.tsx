"use client";

import { useEffect, useRef } from "react";
import type { TurnView } from "@/lib/session-store";
import { TurnBubble } from "./TurnBubble";

const SUGGESTIONS = [
  "I'm C-1001, PIN 4321 — can I get a refund for INV-2207?",
  "What does the Pro plan's support include?",
  "Do you sell Wi-Fi routers?",
];

export function MessageList({ turns, onSuggest }: { turns: TurnView[]; onSuggest: (text: string) => void }) {
  const end = useRef<HTMLDivElement>(null);
  const last = turns[turns.length - 1];
  const signature = `${turns.length}:${last?.answer.length ?? 0}:${last?.steps.length ?? 0}`;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [signature]);

  if (turns.length === 0) {
    return (
      <div className="mx-auto flex h-full max-w-xl flex-col justify-center gap-5 px-1 py-10">
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight">How can Nimbus help?</h1>
        <p className="text-[15px] leading-6 text-ink-soft">
          Ask about plans, billing or a problem you&apos;re having. For anything on your account, have your account
          ID and 4-digit support PIN ready. You can type or switch to voice.
        </p>
        <div className="flex flex-col items-start gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onSuggest(s)}
              className="rounded-lg border border-line bg-surface px-3 py-2 text-left text-sm text-ink hover:border-storm/50"
            >
              {s}
            </button>
          ))}
        </div>
        <p className="text-xs text-ink-soft">Demo accounts are listed in the project README.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 px-1 py-6">
      {turns.map((t) => (
        <TurnBubble key={t.turnId} turn={t} />
      ))}
      <div ref={end} />
    </div>
  );
}
