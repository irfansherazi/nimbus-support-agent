import ReactMarkdown from "react-markdown";
import type { GuardrailView, TurnView } from "@/lib/session-store";
import { StepRail } from "./StepRail";

function GuardrailNote({ g }: { g: GuardrailView }) {
  if (g.band === "skipped") return null;
  const score = g.topScore != null ? g.topScore.toFixed(2) : "–";
  const tone =
    g.band === "high"
      ? "bg-rain-soft text-rain"
      : g.band === "grey"
        ? "bg-amber-soft text-amber"
        : "bg-ember-soft text-ember";
  const text =
    g.band === "high"
      ? `Strong policy match (${score})`
      : g.band === "grey"
        ? g.verify === "supported"
          ? `Partial policy match (${score}), checked against sources`
          : g.verify === "unsupported"
            ? `Partial policy match (${score}), failed the source check`
            : `Partial policy match (${score}), checking…`
        : `No confident policy match (${score})`;
  return <span className={`tabular inline-block rounded px-1.5 py-0.5 text-xs ${tone}`}>{text}</span>;
}

export function TurnBubble({ turn }: { turn: TurnView }) {
  const thinking = turn.status === "running" && !turn.answer && turn.steps.every((s) => s.status !== "running");
  return (
    <article className="space-y-3" aria-live={turn.status === "running" ? "polite" : undefined}>
      {turn.userText && (
        <div className="flex justify-end">
          <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-storm px-4 py-2.5 text-[15px] leading-6 text-white">
            {turn.channel === "voice" && <span className="sr-only">Said aloud: </span>}
            {turn.userText}
          </p>
        </div>
      )}

      <div className="max-w-[92%]">
        <StepRail steps={turn.steps} />

        {turn.retracted && (
          <p className="mb-2 rounded-md border border-amber/40 bg-amber-soft px-3 py-2 text-sm text-amber">
            I removed an answer I couldn&apos;t verify against Nimbus policy.
          </p>
        )}

        {thinking && <p className="text-sm text-ink-soft">Thinking…</p>}

        {turn.answer && (
          <div className="answer text-[15px] leading-7 text-ink">
            <ReactMarkdown skipHtml>{turn.answer}</ReactMarkdown>
            {turn.interrupted && <span className="ml-1 text-sm text-ink-soft">(you interrupted)</span>}
          </div>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {turn.channel === "voice" && <span className="text-xs text-ink-soft">Voice</span>}
          {turn.guardrail && <GuardrailNote g={turn.guardrail} />}
          {turn.escalation && (
            <span className="rounded bg-storm-soft px-1.5 py-0.5 text-xs text-storm">
              Ticket {turn.escalation.ticket_id} opened
            </span>
          )}
          {turn.status === "failed" && turn.error && <span className="text-xs text-ember">Not answered</span>}
        </div>
      </div>
    </article>
  );
}
