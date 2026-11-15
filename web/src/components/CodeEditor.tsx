import { useRef, useState, type KeyboardEvent } from "react";

const LINE_HEIGHT = 22;
const PAD_TOP = 14;

interface Props {
  id: string;
  value: string;
  onChange: (value: string) => void;
  filename: string;
  /** Lines an agent pointed at, with its note. */
  highlight: { from: number; to: number; note: string } | null;
  onDismissHighlight: () => void;
}

/** A plain textarea with a line-number gutter, Tab-to-indent and an agent highlight band. */
export function CodeEditor({ id, value, onChange, filename, highlight, onDismissHighlight }: Props) {
  const [scrollTop, setScrollTop] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const lines = Math.max(value.split("\n").length, 12);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab" || event.shiftKey || event.metaKey || event.ctrlKey) return;
    event.preventDefault();
    const el = event.currentTarget;
    const { selectionStart: start, selectionEnd: end } = el;
    const next = `${value.slice(0, start)}    ${value.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 4; });
  };

  return (
    <div className="editor">
      <div className="editor-bar">
        <span className="editor-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="mono">{filename}</span>
        <span className="editor-lang">Python 3</span>
      </div>
      <div className="editor-body">
        <div className="editor-gutter mono" aria-hidden="true" style={{ transform: `translateY(${-scrollTop}px)` }}>
          {Array.from({ length: lines }, (_, i) => (
            <span key={i} className={highlight && i + 1 >= highlight.from && i + 1 <= highlight.to ? "on" : undefined}>{i + 1}</span>
          ))}
        </div>
        {highlight && (
          <div className="editor-band" aria-hidden="true"
            style={{ top: PAD_TOP + (highlight.from - 1) * LINE_HEIGHT - scrollTop, height: (highlight.to - highlight.from + 1) * LINE_HEIGHT }} />
        )}
        <textarea ref={area} id={id} className="editor-input mono" spellCheck={false} autoCapitalize="off" autoCorrect="off"
          value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)} />
      </div>
      {highlight && (
        <div className="editor-note" role="status">
          <span className="editor-note-tag">Lines {highlight.from}–{highlight.to}</span>
          <span>{highlight.note}</span>
          <button className="btn-ghost btn-small" onClick={onDismissHighlight}>Dismiss</button>
        </div>
      )}
    </div>
  );
}

/** Statement text with `inline code` rendered as code. */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return <>{parts.map((part, i) => (part.startsWith("`") && part.endsWith("`") && part.length > 2
    ? <code key={i} className="inline-code">{part.slice(1, -1)}</code>
    : <span key={i}>{part}</span>))}</>;
}
