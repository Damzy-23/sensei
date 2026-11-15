// Firebase client setup. These values identify the project to Google; they are public by
// design and safe in a browser bundle. Access is controlled by the sign-in providers
// enabled in the Firebase console, not by keeping this config secret.

import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const app = initializeApp({
  apiKey: "AIzaSyCaKC_9ca_rHwSAEjR8V5vy81VyjEkiWhg",
  authDomain: "senior-coach-ai.web.app",
  projectId: "glo-ai-3e547",
  appId: "1:40946072816:web:21757e595177b6db721635",
});

export const auth = getAuth(app);
