"use client";

import { useEffect, useRef } from "react";

/** Live bar waveform drawn from an analyser on every animation frame. */
export function Waveform({ bars, color, label }: { bars: () => number[]; color: string; label: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    const g = el?.getContext("2d");
    if (!el || !g) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (el.width !== w * dpr) {
        el.width = w * dpr;
        el.height = h * dpr;
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const values = bars();
      const n = values.length || 24;
      const gap = 2;
      const bw = (w - gap * (n - 1)) / n;
      g.fillStyle = color;
      for (let i = 0; i < n; i++) {
        const v = values[i] ?? 0;
        const bh = Math.max(2, (reduced ? Math.min(v, 0.15) : v) * h);
        g.fillRect(i * (bw + gap), (h - bh) / 2, bw, bh);
      }
      frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [bars, color]);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <span className="w-14 shrink-0 text-xs text-ink-soft">{label}</span>
      <canvas ref={canvas} className="h-8 min-w-0 flex-1" aria-hidden />
    </div>
  );
}
