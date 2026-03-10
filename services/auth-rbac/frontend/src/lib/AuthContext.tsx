/**
 * AuthContext.tsx — Firebase Auth state for the entire app
 * =========================================================
 * Replaces every localStorage.getItem('isAuthenticated') / localStorage.getItem('user')
 * call in the original codebase.
 *
 * Provides:
 *   - firebaseUser   — raw Firebase User object (or null)
 *   - user           — enriched user with RBAC role from custom claims
 *   - loading        — true while the initial auth state is resolving
 *   - login()        — email+password sign-in → creates server session cookie
 *   - loginWithGoogle() — Google OAuth → creates server session cookie
 *   - logout()       — revokes server session + Firebase sign-out
 *   - hasPermission() — checks a permission string against the user's role
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import {
  signInWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  signOut,
  onAuthStateChanged,
  type User as FirebaseUser,
} from "firebase/auth";
import { auth } from "./firebase";
import { createSession, logoutUser, type BackendRole } from "./api";

// ── Permission sets per role (mirrors backend rbac.py) ────────────────────
const ROLE_PERMISSIONS: Record<BackendRole, string[]> = {
  client: [
    "view_own_case",
    "view_own_documents",
    "upload_documents",
  ],
  admin_staff: [
    "view_all_cases",
    "manage_tasks",
    "log_communications",
    "view_documents",
    "view_notes",
    "manage_users",
  ],
  paralegal: [
    "view_all_cases",
    "manage_tasks",
    "log_communications",
    "view_documents",
    "view_notes",
    "request_documents",
    "upload_documents",
    "add_notes",
    "submit_for_review",
  ],
  junior_partner: [
    "view_all_cases",
    "manage_tasks",
    "log_communications",
    "view_documents",
    "view_notes",
    "request_documents",
    "upload_documents",
    "add_notes",
    "submit_for_review",
    "approve_reject_cases",
    "escalate_cases",
    "view_phi",
  ],
  senior_partner: [
    "view_all_cases",
    "view_own_case",
    "manage_tasks",
    "log_communications",
    "request_documents",
    "upload_documents",
    "view_documents",
    "view_own_documents",
    "add_notes",
    "view_notes",
    "submit_for_review",
    "approve_reject_cases",
    "escalate_cases",
    "view_phi",
    "manage_users",
    "assign_roles",
    "view_reports",
    "view_audit_log",
    "system_admin",
  ],
};

// ── Enriched user type ────────────────────────────────────────────────────
export interface AuthUser {
  uid:          string;
  email:        string;
  displayName:  string;
  role:         BackendRole;
  emailVerified: boolean;
  /** Initials for the avatar circle */
  avatarInitials: string;
}

// ── Context type ─────────────────────────────────────────────────────────
interface AuthContextValue {
  firebaseUser:    FirebaseUser | null;
  user:            AuthUser | null;
  loading:         boolean;
  login:           (email: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  logout:          () => Promise<void>;
  hasPermission:   (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [user, setUser]                 = useState<AuthUser | null>(null);
  const [loading, setLoading]           = useState(true);

  /** Build an AuthUser from a Firebase User + custom claims */
  const buildAuthUser = useCallback(async (fbUser: FirebaseUser): Promise<AuthUser> => {
    // Force-refresh to get the latest custom claims (role, active)
    const tokenResult = await fbUser.getIdTokenResult(true);
    const role = (tokenResult.claims["role"] as BackendRole) ?? "client";

    const parts    = (fbUser.displayName ?? fbUser.email ?? "U").trim().split(" ");
    const initials = parts
      .map((p) => p[0] ?? "")
      .join("")
      .toUpperCase()
      .slice(0, 2);

    return {
      uid:           fbUser.uid,
      email:         fbUser.email ?? "",
      displayName:   fbUser.displayName ?? fbUser.email ?? "User",
      role,
      emailVerified: fbUser.emailVerified,
      avatarInitials: initials,
    };
  }, []);

  // Subscribe to Firebase auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (fbUser) => {
      if (fbUser) {
        const enriched = await buildAuthUser(fbUser);
        setFirebaseUser(fbUser);
        setUser(enriched);
      } else {
        setFirebaseUser(null);
        setUser(null);
      }
      setLoading(false);
    });
    return unsubscribe;
  }, [buildAuthUser]);

  /** Email + password sign-in */
  const login = useCallback(async (email: string, password: string) => {
    const credential = await signInWithEmailAndPassword(auth, email, password);
    // Exchange the ID token for a server-side session cookie
    const idToken = await credential.user.getIdToken();
    await createSession(idToken);
  }, []);

  /** Google OAuth sign-in */
  const loginWithGoogle = useCallback(async () => {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    const credential = await signInWithPopup(auth, provider);
    const idToken    = await credential.user.getIdToken();
    await createSession(idToken);
  }, []);

  /** Sign out — revokes server session and local Firebase session */
  const logout = useCallback(async () => {
    await logoutUser();   // tells backend to revoke + clear cookies
    await signOut(auth);
  }, []);

  /** Check if the current user has a specific permission */
  const hasPermission = useCallback(
    (permission: string): boolean => {
      if (!user) return false;
      return ROLE_PERMISSIONS[user.role]?.includes(permission) ?? false;
    },
    [user]
  );

  return (
    <AuthContext.Provider
      value={{ firebaseUser, user, loading, login, loginWithGoogle, logout, hasPermission }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
