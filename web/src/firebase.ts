// Firebase client setup. These values identify the project to Google; they are public by
// design and safe in a browser bundle. Access is controlled by the sign-in providers
// enabled in the Firebase console, not by keeping this config secret.

import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const app = initializeApp({
  apiKey: "AIzaSyD36I9lW38Bctmm7DBzFe_UeBEuIpOpnnk",
  authDomain: "senior-coach-1115-29b5.firebaseapp.com",
  projectId: "senior-coach-1115-29b5",
  appId: "1:257917415532:web:762511e14b9ad9f1d6a849",
});

export const auth = getAuth(app);
