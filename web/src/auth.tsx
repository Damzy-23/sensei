import {
  GoogleAuthProvider, createUserWithEmailAndPassword, onAuthStateChanged, signInWithEmailAndPassword,
  signInWithPopup, signOut, type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { auth } from "./firebase";
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
        <button className="btn-google" disabled={busy} onClick={() => void attempt(() => signInWithPopup(auth, new GoogleAuthProvider()))}>
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/>
          </svg>
          Continue with Google
        </button>
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
