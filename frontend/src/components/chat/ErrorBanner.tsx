import type { ErrorView } from "@/lib/session-store";

const COPY: Record<string, string> = {
  LLM_UNAVAILABLE: "The assistant is temporarily unavailable. Your message wasn't lost.",
  INTERNAL: "Something went wrong on our side. Your message wasn't lost.",
  RATE_LIMITED: "You're sending messages too quickly. Try again in a minute.",
  BUDGET_EXCEEDED: "The demo has reached today's usage limit. Please come back tomorrow.",
  NETWORK: "Can't reach the support service. Check your connection.",
};

export function ErrorBanner({
  error,
  canRetry,
  onRetry,
  onDismiss,
}: {
  error: ErrorView;
  canRetry: boolean;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div role="alert" className="flex items-center gap-3 rounded-xl border border-ember/30 bg-ember-soft px-3 py-2 text-sm">
      <p className="flex-1 text-ember">{COPY[error.code] ?? error.message}</p>
      {canRetry && (
        <button type="button" onClick={onRetry} className="rounded-lg bg-ember px-3 py-1.5 font-medium text-white">
          Retry
        </button>
      )}
      <button type="button" onClick={onDismiss} className="px-1 text-ember/80 hover:text-ember" aria-label="Dismiss">
        Dismiss
      </button>
    </div>
  );
}
