// Google sign-in through Google Identity Services. Google returns an ID token directly to
// this page, and Firebase signs in with it. Unlike Firebase's popup handler, this does not
// depend on sessionStorage, so it works in Safari, on iPhones and in in-app browsers.
import { GoogleAuthProvider, signInWithCredential, signInWithPopup } from "firebase/auth";
import { useEffect, useRef, useState } from "react";
import { auth } from "./firebase";

const CLIENT_ID = "40946072816-q0trf1on00n6j8u8shhmnho2sb3u3fkq.apps.googleusercontent.com";

interface Gis {
  accounts: { id: {
    initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string; itp_support?: boolean }) => void;
    renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
  } };
}
declare global { interface Window { google?: Gis } }

let loading: Promise<Gis> | null = null;
function loadGis(): Promise<Gis> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => (window.google ? resolve(window.google) : reject(new Error("Google sign-in did not load")));
    s.onerror = () => reject(new Error("Google sign-in did not load"));
    document.head.appendChild(s);
  });
  return loading;
}

export function GoogleButton({ onError, onBusy }: { onError: (err: unknown) => void; onBusy: (busy: boolean) => void }) {
  const slot = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    loadGis().then((gis) => {
      if (!live || !slot.current) return;
      gis.accounts.id.initialize({
        client_id: CLIENT_ID,
        itp_support: true,
        callback: ({ credential }) => {
          onBusy(true);
          signInWithCredential(auth, GoogleAuthProvider.credential(credential)).catch(onError).finally(() => onBusy(false));
        },
      });
      gis.accounts.id.renderButton(slot.current, {
        type: "standard", theme: "filled_white", size: "large", text: "continue_with", shape: "rectangular",
        logo_alignment: "center", width: Math.min(slot.current.clientWidth || 356, 400),
      });
    }, () => live && setFailed(true));
    return () => { live = false; };
  }, [onBusy, onError]);

  if (failed) {
    // Google's script is blocked (an extension or a network): fall back to Firebase's popup.
    return (
      <button className="btn-google" onClick={() => { onBusy(true); signInWithPopup(auth, new GoogleAuthProvider()).catch(onError).finally(() => onBusy(false)); }}>
        Continue with Google
      </button>
    );
  }
  return <div ref={slot} className="gis-slot" aria-label="Continue with Google" />;
}
