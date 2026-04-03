/**
 * AuthContext.tsx
 * Permissions aligned to the Firestore `roles` collection (dot-notation).
 */
import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import {
  signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider,
  signOut, onAuthStateChanged, type User as FirebaseUser,
} from "firebase/auth";
import { auth } from "./firebase";
import { createSession, logoutUser, type BackendRole } from "./api";

// Mirrors Firestore roles collection exactly
const ROLE_PERMISSIONS: Record<BackendRole, string[]> = {
  client: [
    "cases.read",
    "documents.read",
    "documents.upload",
    "communications.read",
    "timeline.read",
  ],
  admin_staff: [
    "cases.read", "cases.write", "cases.status.update",
    "clients.read", "clients.write",
    "documents.read", "documents.upload",
    "tasks.read", "tasks.write", "tasks.complete",
    "communications.read", "communications.write",
    "timeline.read",
    "expenses.read", "expenses.write",
    "disbursements.read",
    "staff.read", "staff.manage",
  ],
  paralegal: [
    "cases.read", "cases.write", "cases.status.update",
    "clients.read", "clients.write",
    "documents.read", "documents.upload", "documents.verify",
    "tasks.read", "tasks.write", "tasks.complete",
    "communications.read", "communications.write",
    "timeline.read",
    "expenses.read", "expenses.write",
    "disbursements.read",
    "staff.read",
    "reports.read",
  ],
  junior_partner: [
    "cases.read", "cases.write", "cases.status.update", "cases.approve",
    "clients.read", "clients.write",
    "documents.read", "documents.upload", "documents.verify",
    "tasks.read", "tasks.write", "tasks.complete",
    "communications.read", "communications.write",
    "timeline.read",
    "expenses.read", "expenses.write",
    "disbursements.read", "disbursements.write",
    "staff.read",
    "reports.read", "analytics.read",
    "settings.read",
  ],
  senior_partner: [
    "cases.read", "cases.write", "cases.status.update", "cases.approve", "cases.delete",
    "clients.read", "clients.write",
    "documents.read", "documents.upload", "documents.verify", "documents.override",
    "tasks.read", "tasks.write", "tasks.complete",
    "communications.read", "communications.write",
    "timeline.read",
    "expenses.read", "expenses.write",
    "disbursements.read", "disbursements.write", "disbursements.approve",
    "staff.read", "staff.write", "staff.manage",
    "reports.read", "analytics.read",
    "settings.read", "settings.write",
    "auditLog.read",
    "system.admin",
  ],
  system_admin: [
    "cases.read", "cases.write", "cases.status.update", "cases.approve", "cases.delete",
    "clients.read", "clients.write",
    "documents.read", "documents.upload", "documents.verify", "documents.override",
    "tasks.read", "tasks.write", "tasks.complete",
    "communications.read", "communications.write",
    "timeline.read",
    "expenses.read", "expenses.write",
    "disbursements.read", "disbursements.write", "disbursements.approve",
    "staff.read", "staff.write", "staff.manage",
    "reports.read", "analytics.read",
    "settings.read", "settings.write",
    "auditLog.read",
    "system.admin",
  ],
};

export interface AuthUser {
  uid: string;
  email: string;
  displayName: string;
  role: BackendRole;
  emailVerified: boolean;
  avatarInitials: string;
}

interface AuthContextValue {
  firebaseUser: FirebaseUser | null;
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [user, setUser]                 = useState<AuthUser | null>(null);
  const [loading, setLoading]           = useState(true);

  const buildAuthUser = useCallback(async (fbUser: FirebaseUser): Promise<AuthUser> => {
    const tokenResult = await fbUser.getIdTokenResult(true);
    const role = (tokenResult.claims["role"] as BackendRole) ?? "client";
    const parts = (fbUser.displayName ?? fbUser.email ?? "U").trim().split(" ");
    const initials = parts.map((p) => p[0] ?? "").join("").toUpperCase().slice(0, 2);
    return {
      uid: fbUser.uid,
      email: fbUser.email ?? "",
      displayName: fbUser.displayName ?? fbUser.email ?? "User",
      role,
      emailVerified: fbUser.emailVerified,
      avatarInitials: initials,
    };
  }, []);

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

  const login = useCallback(async (email: string, password: string) => {
    const credential = await signInWithEmailAndPassword(auth, email, password);
    try {
      const idToken = await credential.user.getIdToken();
      await createSession(idToken);
    } catch { /* session cookie is best-effort */ }
  }, []);

  const loginWithGoogle = useCallback(async () => {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    const credential = await signInWithPopup(auth, provider);
    try {
      const idToken = await credential.user.getIdToken();
      await createSession(idToken);
    } catch { /* session cookie is best-effort */ }
  }, []);

  const logout = useCallback(async () => {
    try { await logoutUser(); } catch { /* best-effort */ }
    await signOut(auth);
    setUser(null);
    setFirebaseUser(null);
  }, []);

  const hasPermission = useCallback((permission: string): boolean => {
    if (!user) return false;
    return ROLE_PERMISSIONS[user.role]?.includes(permission) ?? false;
  }, [user]);

  return (
    <AuthContext.Provider value={{ firebaseUser, user, loading, login, loginWithGoogle, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
