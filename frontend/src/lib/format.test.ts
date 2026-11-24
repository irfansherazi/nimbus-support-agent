import { describe, expect, it } from "vitest";
import { buildSpanTree, formatMs, formatUsd, sumTokens } from "./format";

describe("format", () => {
  it("formats small and normal dollar amounts", () => {
    expect(formatUsd(0.00412)).toBe("$0.0041");
    expect(formatUsd(1.5)).toBe("$1.50");
    expect(formatUsd(0)).toBe("$0.00");
  });

  it("formats milliseconds and seconds", () => {
    expect(formatMs(830)).toBe("830ms");
    expect(formatMs(2300)).toBe("2.3s");
    expect(formatMs(null)).toBe("–");
  });

  it("nests spans by parent and orders children by start", () => {
    const span = (id: string, parent: string | null, start: number) => ({
      span_id: id, parent_id: parent, name: id, kind: "node" as const, start_ms: start, duration_ms: 1, attrs: {},
    });
    const tree = buildSpanTree([span("b", null, 20), span("c", "a", 15), span("a", null, 10), span("d", "a", 12)]);
    expect(tree.map((n) => n.span.span_id)).toEqual(["a", "b"]);
    expect(tree[0].children.map((n) => n.span.span_id)).toEqual(["d", "c"]);
  });

  it("orphan spans become roots", () => {
    const tree = buildSpanTree([{ span_id: "x", parent_id: "missing", name: "x", kind: "llm", start_ms: 0, duration_ms: 1, attrs: {} }]);
    expect(tree).toHaveLength(1);
  });

  it("sums tokens across calls", () => {
    expect(sumTokens([{ input_tokens: 10, output_tokens: 2 }, { input_tokens: 5, output_tokens: 1 }] as never)).toEqual({ input: 15, output: 3 });
  });
});
