import {
  GoogleAuthProvider, createUserWithEmailAndPassword, onAuthStateChanged, signInWithEmailAndPassword,
  signInWithPopup, signOut, type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { auth } from "./firebase";

interface AuthState { user: User | null; guest: boolean; signOut: () => void }
const Ctx = createContext<AuthState>({ user: null, guest: false, signOut: () => undefined });
export const useAuth = () => useContext(Ctx);

/** Firebase error codes, in words a person can act on. */
function explain(err: unknown): string {
  const code = (err as { code?: string }).code ?? "";
  if (code === "auth/operation-not-allowed" || code === "auth/configuration-not-found")
    return "This sign-in method is not switched on for the project yet. Enable it in the Firebase console under Authentication.";
  if (code === "auth/invalid-credential" || code === "auth/wrong-password" || code === "auth/user-not-found")
    return "That email and password do not match an account.";
  if (code === "auth/email-already-in-use") return "An account with that email already exists. Sign in instead.";
  if (code === "auth/weak-password") return "Use a password of at least 6 characters.";
  if (code === "auth/popup-closed-by-user") return "The Google window was closed before sign-in finished.";
  if (code === "auth/unauthorized-domain") return "This address is not on the project's list of authorised domains.";
  return err instanceof Error ? err.message : String(err);
}

function SignIn({ onGuest }: { onGuest: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await action(); } catch (err) { setError(explain(err)); } finally { setBusy(false); }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void attempt(() => signInWithEmailAndPassword(auth, email, password));
  };

  return (
    <main className="page" style={{ alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
      <section className="card" aria-label="Sign in" style={{ width: "min(420px, 100%)", display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div className="label">Senior</div>
          <h1 style={{ marginTop: 4 }}>Sign in</h1>
          <p className="muted" style={{ margin: "8px 0 0" }}>A coach that gives hints, not answers, and shows its reasoning.</p>
        </div>
        <button className="btn-primary" disabled={busy} onClick={() => void attempt(() => signInWithPopup(auth, new GoogleAuthProvider()))}>
          Continue with Google
        </button>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <label className="label" htmlFor="password">Password</label>
          <input id="password" className="input" type="password" autoComplete="current-password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button type="submit" className="btn-ghost" disabled={busy}>Sign in</button>
            <button type="button" className="btn-ghost" disabled={busy || !email || password.length < 6}
              onClick={() => void attempt(() => createUserWithEmailAndPassword(auth, email, password))}>
              Create account
            </button>
          </div>
        </form>
        {error && <div className="bubble notice" role="alert">{error}</div>}
        <button className="btn-ghost" onClick={onGuest}>Continue as a guest</button>
        <span className="dim" style={{ fontSize: 12 }}>Guest sessions are not tied to an account.</span>
      </section>
    </main>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = still checking
  const [guest, setGuest] = useState(false);
  useEffect(() => onAuthStateChanged(auth, setUser), []);

  if (user === undefined) return <main className="page"><span className="muted">Checking your sign-in…</span></main>;
  if (!user && !guest) return <SignIn onGuest={() => setGuest(true)} />;
  const leave = () => { setGuest(false); void signOut(auth); };
  return <Ctx.Provider value={{ user: user ?? null, guest, signOut: leave }}>{children}</Ctx.Provider>;
}
