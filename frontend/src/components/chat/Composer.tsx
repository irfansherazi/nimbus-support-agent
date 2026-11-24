"use client";

import { useState, type ReactNode } from "react";

export function Composer({
  onSend,
  busy,
  voiceSlot,
}: {
  onSend: (text: string) => void;
  busy: boolean;
  voiceSlot?: ReactNode;
}) {
  const [text, setText] = useState("");

  function submit() {
    const value = text.trim();
    if (!value) return;
    onSend(value);
    setText("");
  }

  return (
    <form
      className="flex items-end gap-2 rounded-2xl border border-line bg-surface p-2 shadow-[0_1px_0_rgb(26_31_46/0.04)]"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="composer" className="sr-only">
        Message
      </label>
      <textarea
        id="composer"
        rows={1}
        value={text}
        maxLength={2000}
        placeholder={busy ? "The assistant is working on your last message…" : "Type your message"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-6 outline-none placeholder:text-ink-soft"
      />
      {voiceSlot}
      <button
        type="submit"
        disabled={!text.trim()}
        className="h-10 rounded-xl bg-storm px-4 text-sm font-medium text-white disabled:opacity-40"
      >
        Send
      </button>
    </form>
  );
}
