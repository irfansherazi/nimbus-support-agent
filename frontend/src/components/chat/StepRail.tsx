import type { StepView } from "@/lib/session-store";

const ERROR_TEXT: Record<string, string> = {
  NOT_VERIFIED: "needs verification",
  VERIFICATION_LOCKED: "verification locked",
  INVALID_CREDENTIALS: "ID or PIN didn't match",
  CONTRACT_NOT_ACTIVE: "contract not active",
  INVOICE_NOT_FOUND: "invoice not found",
  REFUND_NOT_ELIGIBLE: "plan not eligible",
  OUTSIDE_REFUND_WINDOW: "outside refund window",
  AMOUNT_EXCEEDS_LIMIT: "over plan limit",
  INVALID_AMOUNT: "invalid amount",
  INVALID_VALUE: "invalid value",
  TOOL_FAILED: "system didn't respond",
};

function doneLabel(step: StepView): string {
  // "Verifying account & tier…" -> "Verifying account & tier"
  return step.label.replace(/…$/, "");
}

/** The agent's tool chain for one turn, drawn as nodes on a line: the sequence is the information. */
export function StepRail({ steps }: { steps: StepView[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="relative mb-3 ml-1.5 border-l-2 border-storm/25 pl-5" aria-label="Steps the assistant took">
      {steps.map((step) => (
        <li key={step.stepId} className="relative py-1 text-sm leading-5">
          <span
            aria-hidden
            className={[
              "absolute -left-[27px] top-[7px] h-3 w-3 rounded-full border-2",
              step.status === "running" && "node-running border-storm bg-surface",
              step.status === "done" && (step.kind === "system" ? "border-amber bg-amber" : "border-rain bg-rain"),
              step.status === "failed" && "border-ember bg-ember",
            ]
              .filter(Boolean)
              .join(" ")}
          />
          <span
            className={
              step.kind === "system" ? "text-amber" : step.status === "failed" ? "text-ember" : "text-ink"
            }
          >
            {step.status === "running" ? step.label : doneLabel(step)}
          </span>
          {step.status === "failed" && step.error && (
            <span className="text-ember/80"> — {ERROR_TEXT[step.error] ?? step.error.toLowerCase()}</span>
          )}
          {step.status !== "running" && step.durationMs != null && (
            <span className="tabular ml-2 text-xs text-ink-soft">{formatMs(step.durationMs)}</span>
          )}
        </li>
      ))}
    </ol>
  );
}

export function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}
