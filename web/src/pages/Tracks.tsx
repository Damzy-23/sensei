import { patternName } from "../labels";
import { useEffect, useMemo, useState } from "react";
import { getTrack, listTracks, type Difficulty, type Track, type TrackProblem, type TrackSummary } from "../api";
import { useApp } from "../app-context";

const DIFFICULTY_CLASS: Record<Difficulty, string> = { easy: "seafoam", medium: "baltic", hard: "sky" };

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

function groupByPattern(problems: TrackProblem[]): [string, TrackProblem[]][] {
  const groups = new Map<string, TrackProblem[]>();
  for (const problem of problems) {
    const list = groups.get(problem.pattern);
    if (list) list.push(problem);
    else groups.set(problem.pattern, [problem]);
  }
  return [...groups.entries()];
}

export function Tracks() {
  const { openProblem } = useApp();
  const [tracks, setTracks] = useState<Load<TrackSummary[]>>({ status: "loading" });
  const [trackId, setTrackId] = useState<string | null>(null);
  const [track, setTrack] = useState<Load<Track>>({ status: "loading" });
  const [query, setQuery] = useState("");

  useEffect(() => {
    let current = true;
    listTracks().then(
      (data) => {
        if (!current) return;
        setTracks({ status: "ready", data });
        setTrackId((existing) => existing ?? data[0]?.id ?? null);
      },
      (err: Error) => current && setTracks({ status: "error", message: err.message }),
    );
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!trackId) return;
    let current = true;
    setTrack({ status: "loading" });
    getTrack(trackId).then(
      (data) => current && setTrack({ status: "ready", data }),
      (err: Error) => current && setTrack({ status: "error", message: err.message }),
    );
    return () => { current = false; };
  }, [trackId]);

  const groups = useMemo(() => {
    if (track.status !== "ready") return [];
    const needle = query.trim().toLowerCase();
    const shown = needle ? track.data.problems.filter((p) => p.title.toLowerCase().includes(needle)) : track.data.problems;
    return groupByPattern(shown);
  }, [track, query]);

  return (
    <main className="page">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "12px 24px" }}>
        <div>
          <div className="label">Your map</div>
          <h1 style={{ marginTop: 4, fontSize: 34, lineHeight: "38px", letterSpacing: -1 }}>Patterns, one at a time</h1>
        </div>
        <div style={{ marginLeft: "auto", minWidth: 240, flex: "0 1 320px" }}>
          <label className="label" htmlFor="track-search" style={{ display: "block", marginBottom: 6 }}>Search problems</label>
          <input id="track-search" className="input" type="search" placeholder="Title, for example Two Sum" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {tracks.status === "loading" && <div className="muted">Loading tracks…</div>}
      {tracks.status === "error" && <div className="bubble notice" role="alert">Could not load the tracks: {tracks.message}</div>}
      {tracks.status === "ready" && tracks.data.length === 0 && <div className="muted">No tracks are available yet.</div>}
      {tracks.status === "ready" && tracks.data.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }} role="group" aria-label="Track">
          {tracks.data.map((t) => (
            <button key={t.id} className={`filter ${t.id === trackId ? "on" : ""}`} aria-pressed={t.id === trackId} onClick={() => setTrackId(t.id)}>
              {t.title}{!t.title.includes(String(t.count)) && <span className="mono dim"> {t.count}</span>}
            </button>
          ))}
          <span className="dim" style={{ fontSize: 12, alignSelf: "center", marginLeft: 6 }}>
            <span className="pill seafoam" style={{ marginRight: 6 }}>Ready</span>has runnable tests. The coach helps with every problem.
          </span>
        </div>
      )}

      {trackId && track.status === "loading" && <div className="muted">Loading problems…</div>}
      {trackId && track.status === "error" && <div className="bubble notice" role="alert">Could not load this track: {track.message}</div>}
      {track.status === "ready" && groups.length === 0 && <div className="muted">No problems match.</div>}

      {track.status === "ready" && groups.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(360px, 100%), 1fr))", gap: 18, alignItems: "start" }}>
          {groups.map(([pattern, problems]) => (
            <section key={pattern} className="card" aria-label={`${patternName(pattern)}, ${problems.length} problems`}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
                <h2>{patternName(pattern)}</h2>
                <span className="mono dim" style={{ marginLeft: "auto", fontSize: 12 }}>{problems.length}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {problems.map((problem) => (
                  <button
                    key={problem.id}
                    onClick={() => openProblem(problem.id)}
                    className="btn-ghost"
                    style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", height: "auto", minHeight: 44, padding: "8px 12px", textAlign: "left" }}
                  >
                    <span style={{ flex: 1, minWidth: 0 }}>{problem.title}</span>
                    <span className={`pill ${DIFFICULTY_CLASS[problem.difficulty]}`} style={{ textTransform: "capitalize" }}>{problem.difficulty}</span>
                    {problem.runnable ? (
                      <span className="pill seafoam" title="Has a full statement and runnable tests">Ready</span>
                    ) : null}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </main>
  );
}
