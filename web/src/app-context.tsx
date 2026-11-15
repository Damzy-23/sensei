import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createSession, type Mode } from "./api";

export type PageId = "workspace" | "tracks" | "blitz" | "inspector" | "mentor";

interface AppState {
  page: PageId;
  go: (page: PageId) => void;
  mode: Mode;
  sessionId: string | null;
  sessionError: string | null;
  /** Switching mode starts a new session: the mode decides which agent answers. */
  setMode: (mode: Mode) => void;
  problemId: string;
  openProblem: (problemId: string) => void;
}

const Ctx = createContext<AppState | null>(null);
const PAGES: PageId[] = ["workspace", "tracks", "blitz", "inspector", "mentor"];
const pageFromHash = (): PageId => {
  const hash = window.location.hash.slice(1) as PageId;
  return PAGES.includes(hash) ? hash : "workspace";
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageId>(pageFromHash);
  const [mode, setModeState] = useState<Mode>("learn");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [problemId, setProblemId] = useState("two-sum");

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let current = true;
    setSessionId(null);
    setSessionError(null);
    createSession(mode).then(
      (id) => current && setSessionId(id),
      (err: Error) => current && setSessionError(`Could not reach the Senior API: ${err.message}`),
    );
    return () => { current = false; };
  }, [mode]);

  const go = useCallback((next: PageId) => { window.location.hash = next; }, []);
  const openProblem = useCallback((id: string) => { setProblemId(id); window.location.hash = "workspace"; }, []);

  const value = useMemo<AppState>(
    () => ({ page, go, mode, sessionId, sessionError, setMode: setModeState, problemId, openProblem }),
    [page, go, mode, sessionId, sessionError, problemId, openProblem],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}

export const MODE_COLOR: Record<Mode, string> = { learn: "var(--seafoam)", interview: "var(--baltic)", blitz: "var(--sky)", call: "var(--baltic)" };
