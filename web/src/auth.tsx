// Google sign-in through Firebase. Turned off with VITE_AUTH=off (local dev without an account).
import { initializeApp } from "firebase/app";
import { GoogleAuthProvider, getAuth, onIdTokenChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const env = import.meta.env;
export const AUTH_ON = env.VITE_AUTH !== "off";

// A Firebase web config is public by design; access is enforced by the API checking the token.
const firebaseApp = initializeApp({
  apiKey: env.VITE_FIREBASE_API_KEY ?? "AIzaSyCaKC_9ca_rHwSAEjR8V5vy81VyjEkiWhg",
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN ?? "senior-coach.web.app",
  projectId: env.VITE_FIREBASE_PROJECT_ID ?? "glo-ai-3e547",
  appId: env.VITE_FIREBASE_APP_ID ?? "1:40946072816:web:21757e595177b6db721635",
});
const auth = getAuth(firebaseApp);

/** The current user's ID token, refreshed when near expiry. Null when signed out or auth is off. */
export async function idToken(): Promise<string | null> {
  if (!AUTH_ON) return null;
  return auth.currentUser ? auth.currentUser.getIdToken() : null;
}

interface AuthState { user: User | null; ready: boolean; signIn: () => Promise<void>; signOut: () => Promise<void> }
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(!AUTH_ON);
  useEffect(() => {
    if (!AUTH_ON) return;
    return onIdTokenChanged(auth, (next) => { setUser(next); setReady(true); });
  }, []);
  const value: AuthState = {
    user, ready,
    signIn: async () => { await signInWithPopup(auth, new GoogleAuthProvider()); },
    signOut: () => signOut(auth),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/** Renders its children only once someone is signed in (or auth is off). */
export function SignInGate({ children, logo }: { children: ReactNode; logo: ReactNode }) {
  const { user, ready, signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!AUTH_ON || user) return <>{children}</>;
  if (!ready) return <main className="signin" aria-busy="true" />;
  const start = async () => {
    setBusy(true); setError(null);
    try { await signIn(); }
    catch (err) {
      const code = (err as { code?: string }).code ?? "";
      if (!code.includes("popup-closed") && !code.includes("cancelled-popup")) setError("Sign-in didn't work. Try again.");
    } finally { setBusy(false); }
  };
  return (
    <main className="signin">
      <div className="signin-card">
        {logo}
        <h1>Senior</h1>
        <p className="muted">Graded hints for coding interviews, never the answer. Sign in to keep your progress.</p>
        <button className="btn-primary" onClick={start} disabled={busy}>{busy ? "Signing in…" : "Continue with Google"}</button>
        {error && <p className="signin-error" role="alert">{error}</p>}
      </div>
    </main>
  );
}
