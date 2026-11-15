// The glass: a panel the agent draws on while it talks. Everything here is driven by page
// tools (glass_array, glass_steps, glass_note, glass_clear), so the agent's drawings go
// through the same registry, and the same limits, as every other action it takes.

import { useEffect, useState } from "react";
import { registerTool } from "./tools";

type Item =
  | { id: number; kind: "array"; values: string[]; pointers: Map<number, string[]>; caption: string }
  | { id: number; kind: "steps"; title: string; steps: string[] }
  | { id: number; kind: "note"; text: string };

type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;
type NewItem = WithoutId<Item>;

const MAX_ITEMS = 4;
const MAX_CELLS = 16;
const LOOKS_LIKE_CODE = /```|^\s*(def |for .+ in .+:|while .+:|return\b|import )/m;

/** "0:left,4:right" -> {0: [left], 4: [right]}. Entries that do not parse are dropped. */
function parsePointers(text: string, length: number): Map<number, string[]> {
  const out = new Map<number, string[]>();
  for (const part of text.split(",")) {
    const [index, label] = part.split(":").map((s) => s.trim());
    const i = Number(index);
    if (label && Number.isInteger(i) && i >= 0 && i < length) out.set(i, [...(out.get(i) ?? []), label]);
  }
  return out;
}

/** The glass is words and pictures. Code on it would bypass the coach's leak check. */
function refuseCode(...texts: string[]): void {
  if (texts.some((t) => LOOKS_LIKE_CODE.test(t))) throw new Error("The glass does not show code. Describe it in words.");
}

export function Glass() {
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    let nextId = 0;
    const add = (item: NewItem) => {
      setItems((list) => [...list, { ...item, id: nextId++ } as Item].slice(-MAX_ITEMS));
      return { drawn: 1 };
    };
    const cleanups = [
      registerTool("glass_array", ({ values, pointers, caption }) => {
        if (!Array.isArray(values) || values.length === 0) throw new Error("values must be a non-empty list.");
        if (values.length > MAX_CELLS) throw new Error(`Draw at most ${MAX_CELLS} cells.`);
        refuseCode(caption ?? "");
        const cells = values.map(String);
        return add({ kind: "array", values: cells, pointers: parsePointers(pointers ?? "", cells.length), caption: caption ?? "" });
      }),
      registerTool("glass_steps", ({ title, steps }) => {
        if (!Array.isArray(steps) || steps.length === 0) throw new Error("steps must be a non-empty list.");
        refuseCode(title ?? "", ...steps.map(String));
        return add({ kind: "steps", title: title ?? "", steps: steps.map(String).slice(0, 6) });
      }),
      registerTool("glass_note", ({ text }) => {
        if (!text?.trim()) throw new Error("text is empty.");
        refuseCode(text);
        return add({ kind: "note", text });
      }),
      registerTool("glass_clear", () => { setItems([]); return {}; }),
    ];
    return () => cleanups.forEach((off) => off());
  }, []);

  if (items.length === 0) return null;
  return (
    <aside aria-label="Glass" aria-live="polite" className="glass">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="label">Glass · drawn by Senior</span>
        <button className="btn-ghost" style={{ height: 30, marginLeft: "auto", padding: "0 12px" }} onClick={() => setItems([])}>Clear</button>
      </div>
      {items.map((item) => (
        <div key={item.id} className="glass-item">
          {item.kind === "array" && (
            <figure style={{ margin: 0 }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {item.values.map((value, i) => (
                  <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, minWidth: 44 }}>
                    <span className="dim mono" style={{ fontSize: 10 }}>{i}</span>
                    <span className="glass-cell" data-pointed={item.pointers.has(i) || undefined}>{value}</span>
                    <span className="mono sky" style={{ fontSize: 11, minHeight: 16 }}>{item.pointers.get(i)?.join(" ") ?? ""}</span>
                  </div>
                ))}
              </div>
              {item.caption && <figcaption className="muted" style={{ fontSize: 13, marginTop: 6 }}>{item.caption}</figcaption>}
            </figure>
          )}
          {item.kind === "steps" && (
            <>
              {item.title && <div style={{ font: "700 15px var(--display)" }}>{item.title}</div>}
              <ol style={{ margin: "6px 0 0", paddingLeft: 20, fontSize: 13, lineHeight: "21px" }}>
                {item.steps.map((step, i) => <li key={i}>{step}</li>)}
              </ol>
            </>
          )}
          {item.kind === "note" && <div style={{ fontSize: 13, lineHeight: "20px" }}>{item.text}</div>}
        </div>
      ))}
    </aside>
  );
}
