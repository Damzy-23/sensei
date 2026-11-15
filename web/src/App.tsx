import { useApp, type PageId } from "./app-context";
import { Glass } from "./agent/Glass";
import { VoiceAgent } from "./agent/VoiceAgent";
import { useAuth } from "./auth";
import { Blitz } from "./pages/Blitz";
import { CvStudio } from "./pages/CvStudio";
import { Inspector } from "./pages/Inspector";
import { Logs } from "./pages/Logs";
import { Mentor } from "./pages/Mentor";
import { Profile } from "./pages/Profile";
import { Tracks } from "./pages/Tracks";
import { Workspace } from "./pages/Workspace";

const NAV: { id: PageId; label: string }[] = [
  { id: "workspace", label: "Workspace" },
  { id: "tracks", label: "Learn path" },
  { id: "blitz", label: "Blitz lab" },
  { id: "profile", label: "Profile" },
  { id: "cv", label: "CV studio" },
  { id: "inspector", label: "Agent inspector" },
  { id: "mentor", label: "Mentor" },
  { id: "logs", label: "Activity log" },
];

function Logo() {
  return (
    <span className="brand-mark">
      <svg width="24" height="28" viewBox="380 230 520 720" aria-hidden="true">
        <defs>
          <linearGradient id="sensei-mark" gradientUnits="userSpaceOnUse" x1="440" y1="260" x2="860" y2="900">
            <stop offset="0" stopColor="#86BBD8" />
            <stop offset="1" stopColor="#5F9CC4" />
          </linearGradient>
        </defs>
        <path d="M780 313 L560 382 C480 410 445 450 445 475 C445 510 480 535 545 555 L740 622 C790 640 822 675 822 710 C822 750 790 785 735 805 L483 871" fill="none" stroke="url(#sensei-mark)" strokeWidth="100" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function App() {
  const { page, go, sessionError } = useApp();
  const { user, signOut } = useAuth();
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><Logo />Senior</div>
        <nav className="nav" aria-label="Screens">
          {NAV.map((item) => (
            <button key={item.id} className={page === item.id ? "on" : ""} aria-current={page === item.id ? "page" : undefined} onClick={() => go(item.id)}>
              {item.label}
            </button>
          ))}
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <VoiceAgent />
          <span className="muted" style={{ fontSize: 12 }}>{user ? user.displayName ?? user.email : "Guest"}</span>
          <button className="btn-ghost" style={{ height: 36 }} onClick={signOut}>{user ? "Sign out" : "Sign in"}</button>
        </div>
      </header>
      {sessionError && <div className="bubble notice" role="alert" style={{ margin: "16px 28px 0" }}>{sessionError}</div>}
      {/* Workspace stays mounted so a conversation survives a visit to another screen. */}
      <div style={{ display: page === "workspace" ? "contents" : "none" }}><Workspace /></div>
      {page === "tracks" && <Tracks />}
      {page === "blitz" && <Blitz />}
      {page === "cv" && <CvStudio />}
      {/* Profile stays mounted too, so an interview in progress is not lost. */}
      <div style={{ display: page === "profile" ? "contents" : "none" }}><Profile /></div>
      {page === "inspector" && <Inspector />}
      {page === "mentor" && <Mentor />}
      {page === "logs" && <Logs />}
      <Glass />
    </div>
  );
}
