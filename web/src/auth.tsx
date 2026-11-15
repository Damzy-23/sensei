import {
  GoogleAuthProvider, createUserWithEmailAndPassword, onAuthStateChanged, signInWithEmailAndPassword,
  signOut, type User,
} from "firebase/auth";
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { auth } from "./firebase";
import { GoogleButton } from "./GoogleButton";
import { Landing, Logo } from "./pages/Landing";

interface AuthState { user: User | null; guest: boolean; signOut: () => void }
const Ctx = createContext<AuthState>({ user: null, guest: false, signOut: () => undefined });
export const useAuth = () => useContext(Ctx);

/** The signed-in user's ID token for API calls, refreshed by Firebase when it is near expiry.
 *  Null for a guest: the API decides whether a guest is allowed. */
export async function idToken(): Promise<string | null> {
  await auth.authStateReady();
  return auth.currentUser ? auth.currentUser.getIdToken() : null;
}

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

function SignIn({ onGuest, onBack }: { onGuest: () => void; onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reportError = useCallback((err: unknown) => setError(explain(err)), []);
  const attempt = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await action(); } catch (err) { setError(explain(err)); } finally { setBusy(false); }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void attempt(() => signInWithEmailAndPassword(auth, email, password));
  };

  return (
    <main className="signin">
      <section className="signin-card" aria-label="Sign in">
        <button type="button" className="linklike signin-back" onClick={onBack}>← Back</button>
        <Logo />
        <div>
          <h1>Sign in to Senior</h1>
          <p className="muted">A coach that gives hints, not answers, and shows its reasoning.</p>
        </div>
        <GoogleButton onError={reportError} onBusy={setBusy} />
        <div className="signin-or" aria-hidden="true"><span>or with email</span></div>
        <form onSubmit={submit} className="signin-form">
          <label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <label className="label" htmlFor="password">Password</label>
          <input id="password" className="input" type="password" autoComplete="current-password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="signin-row">
            <button type="submit" className="btn-ghost" disabled={busy}>Sign in</button>
            <button type="button" className="btn-ghost" disabled={busy || !email || password.length < 6}
              onClick={() => void attempt(() => createUserWithEmailAndPassword(auth, email, password))}>
              Create account
            </button>
          </div>
        </form>
        {error && <div className="bubble notice" role="alert">{error}</div>}
        <div className="signin-guest">
          <button className="linklike" onClick={onGuest}>Try it as a guest</button>
          <span className="dim">Nothing is saved to an account.</span>
        </div>
        <p className="signin-legal">By continuing you agree to the <a href="/tos">terms</a> and the <a href="/privacy">privacy policy</a>.</p>
      </section>
    </main>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = still checking
  const [guest, setGuest] = useState(false);
  const [started, setStarted] = useState(false);
  useEffect(() => onAuthStateChanged(auth, setUser), []);

  if (user === undefined) return <main className="page"><span className="muted">Checking your sign-in…</span></main>;
  if (!user && !guest) return started ? <SignIn onGuest={() => setGuest(true)} onBack={() => setStarted(false)} /> : <Landing onStart={() => setStarted(true)} />;
  const leave = () => { setGuest(false); setStarted(true); void signOut(auth); };
  return <Ctx.Provider value={{ user: user ?? null, guest, signOut: leave }}>{children}</Ctx.Provider>;
}
