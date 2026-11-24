"use client";

import { useEffect, useState } from "react";
import { Composer } from "@/components/chat/Composer";
import { ErrorBanner } from "@/components/chat/ErrorBanner";
import { MessageList } from "@/components/chat/MessageList";
import { StatusBar } from "@/components/header/StatusBar";
import { useSession } from "@/hooks/useSession";

const DRAWER_KEY = "nimbus.drawerOpen";

export default function Home() {
  const { state, stream, send, retry, newConversation } = useSession();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dismissedError, setDismissedError] = useState<unknown>(null);

  useEffect(() => {
    try {
      setDrawerOpen(window.localStorage.getItem(DRAWER_KEY) === "1");
    } catch {
      /* storage unavailable */
    }
  }, []);

  function toggleDrawer() {
    setDrawerOpen((open) => {
      try {
        window.localStorage.setItem(DRAWER_KEY, open ? "0" : "1");
      } catch {
        /* storage unavailable */
      }
      return !open;
    });
  }

  const busy = state.turns.some((t) => t.status === "running");
  const error = state.error && state.error !== dismissedError ? state.error : null;

  return (
    <div className="flex h-dvh flex-col">
      <StatusBar
        state={state}
        stream={stream}
        drawerOpen={drawerOpen}
        onToggleDrawer={toggleDrawer}
        onNew={() => void newConversation()}
      />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 sm:px-6">
            <MessageList turns={state.turns} onSuggest={(t) => void send(t)} />
          </div>
          <div className="mx-auto w-full max-w-2xl space-y-2 px-4 pb-4 sm:px-1">
            {error && (
              <ErrorBanner
                error={error}
                canRetry={Boolean(state.pendingRetry)}
                onRetry={() => void retry()}
                onDismiss={() => setDismissedError(state.error)}
              />
            )}
            <Composer onSend={(t) => void send(t)} busy={busy} />
          </div>
        </main>
        {drawerOpen && (
          <aside
            id="observability"
            className="hidden w-[380px] shrink-0 border-l border-line bg-surface lg:block"
            aria-label="Agent trace"
          >
            <p className="p-4 text-sm text-ink-soft">The trace panel arrives in the next step.</p>
          </aside>
        )}
      </div>
    </div>
  );
}
