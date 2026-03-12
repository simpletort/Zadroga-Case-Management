/**
 * firebase.ts — Firebase App initialization
 * ==========================================
 * Single import point for all Firebase services used by the frontend.
 *
 * Replace the firebaseConfig values with your actual project config from:
 *   Firebase Console → Project Settings → Your apps → SDK setup
 *
 * For local development with emulators, set:
 *   VITE_USE_EMULATORS=true
 */

import { initializeApp, getApps } from "firebase/app";
import { getAuth, connectAuthEmulator } from "firebase/auth";
import { getFirestore, connectFirestoreEmulator } from "firebase/firestore";

const firebaseConfig = {
  apiKey:            import.meta.env.VITE_FIREBASE_API_KEY             ?? "",
  authDomain:        import.meta.env.VITE_FIREBASE_AUTH_DOMAIN         ?? "simple-tort-zadroga-prod.firebaseapp.com",
  projectId:         import.meta.env.VITE_FIREBASE_PROJECT_ID          ?? "simple-tort-zadroga-prod",
  storageBucket:     import.meta.env.VITE_FIREBASE_STORAGE_BUCKET      ?? "simple-tort-zadroga-prod.firebasestorage.app",
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID ?? "",
  appId:             import.meta.env.VITE_FIREBASE_APP_ID               ?? "",
};

// Prevent duplicate initialisation during hot-reload
const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];

export const auth = getAuth(app);
export const db   = getFirestore(app);

// ── Emulator connections (local development) ──────────────────────────────
if (import.meta.env.VITE_USE_EMULATORS === "true") {
  connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true });
  connectFirestoreEmulator(db, "localhost", 8080);
}

export default app;
