import React, { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router";
import { ChevronLeft, Save, Mail, Shield, User, Lock } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { Button } from "../ui/button";
import { useToast } from "../ui/toast-provider";
import { createUser, getUser, updateUser, deleteUser, BACKEND_ROLE_LABELS, type BackendRole, type ApiUser } from "../../lib/api";

const ROLES: BackendRole[] = ["senior_partner","junior_partner","paralegal","admin_staff","client"];

const ROLE_PERMISSION_SUMMARY: Record<BackendRole, string> = {
  senior_partner: "Full system access including all cases, user management, audit log, and financial tools.",
  junior_partner: "Can review and approve cases, view PHI, escalate, and access reports.",
  paralegal:      "Can manage cases, upload documents, add notes, and submit for attorney review.",
  admin_staff:    "Can view all cases, manage tasks, log communications, and manage users.",
  client:         "Can view their own case, upload documents, and see client-visible notes.",
};

export function UserForm() {
  const navigate      = useNavigate();
  const { userId }    = useParams();
  const { addToast }  = useToast();
  const isEdit        = !!userId;

  const [existingUser, setExistingUser] = useState<ApiUser | null>(null);
  const [name,      setName]      = useState("");
  const [email,     setEmail]     = useState("");
  const [password,  setPassword]  = useState("");
  const [role,      setRole]      = useState<BackendRole>("paralegal");
  const [status,    setStatus]    = useState<"active" | "inactive">("active");
  const [loading,   setLoading]   = useState(false);
  const [fetching,  setFetching]  = useState(isEdit);

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      try {
        const { user } = await getUser(userId!);
        setExistingUser(user);
        setName(user.display_name);
        setEmail(user.email);
        setRole(user.role);
        setStatus(user.status === "deleted" ? "inactive" : user.status);
      } catch (err) {
        addToast({ message: err instanceof Error ? err.message : "Failed to load user", type: "error" });
        navigate("/admin/users");
      } finally {
        setFetching(false);
      }
    })();
  }, [isEdit, userId, addToast, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (isEdit) {
        await updateUser({ uid: userId!, display_name: name, role, status });
        addToast({ message: "User updated successfully", type: "success" });
      } else {
        await createUser({ email, password, display_name: name, role });
        addToast({ message: "User created successfully", type: "success" });
      }
      navigate("/admin/users");
    } catch (err) {
      addToast({ message: err instanceof Error ? err.message : "Save failed", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!userId || !confirm(`Delete ${name}? This action cannot be undone.`)) return;
    setLoading(true);
    try {
      await deleteUser(userId);
      addToast({ message: "User deleted", type: "success" });
      navigate("/admin/users");
    } catch (err) {
      addToast({ message: err instanceof Error ? err.message : "Delete failed", type: "error" });
      setLoading(false);
    }
  };

  if (fetching) {
    return <div className="flex items-center justify-center py-24"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" /></div>;
  }

  return (
    <div>
      <div className="mb-6">
        <Button variant="ghost" leftIcon={<ChevronLeft className="w-4 h-4" />} onClick={() => navigate("/admin/users")} className="mb-4">
          Back to Users
        </Button>
        <h2 className="text-2xl font-bold text-slate-900">{isEdit ? "Edit User" : "Create New User"}</h2>
        <p className="text-slate-600 mt-1">{isEdit ? "Update user information and role" : "Add a new user to the system"}</p>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card><CardContent className="p-6">
              <h3 className="text-lg font-bold text-slate-900 mb-4">Basic Information</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Full Name *</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input type="text" required value={name} onChange={(e) => setName(e.target.value)}
                      placeholder="John Smith" disabled={loading}
                      className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Email Address *</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                      placeholder="john.smith@simpletort.com" disabled={loading || isEdit}
                      className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:bg-slate-50" />
                  </div>
                  {isEdit && <p className="text-xs text-slate-500 mt-1">Email cannot be changed after creation.</p>}
                </div>
                {!isEdit && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Temporary Password *</label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                      <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                        placeholder="Min 8 chars, 1 upper, 1 number, 1 special" disabled={loading}
                        className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50" />
                    </div>
                  </div>
                )}
              </div>
            </CardContent></Card>

            <Card><CardContent className="p-6">
              <h3 className="text-lg font-bold text-slate-900 mb-4">Role & Status</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Role *</label>
                  <select required value={role} onChange={(e) => setRole(e.target.value as BackendRole)} disabled={loading}
                    className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50">
                    {ROLES.map((r) => <option key={r} value={r}>{BACKEND_ROLE_LABELS[r]}</option>)}
                  </select>
                </div>
                {isEdit && (
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">Status</label>
                    <select value={status} onChange={(e) => setStatus(e.target.value as "active" | "inactive")} disabled={loading}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50">
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                    </select>
                  </div>
                )}
              </div>
            </CardContent></Card>
          </div>

          <div className="space-y-6">
            <Card><CardContent className="p-6">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-5 h-5 text-blue-600" />
                <h3 className="font-bold text-slate-900">Role Info</h3>
              </div>
              <p className="text-sm text-slate-700">{ROLE_PERMISSION_SUMMARY[role]}</p>
            </CardContent></Card>

            <Card><CardContent className="p-6">
              <h3 className="font-bold text-slate-900 mb-4">Actions</h3>
              <div className="space-y-2">
                <Button type="submit" variant="primary" fullWidth leftIcon={<Save className="w-4 h-4" />} disabled={loading}>
                  {loading ? "Saving…" : isEdit ? "Update User" : "Create User"}
                </Button>
                <Button type="button" variant="outline" fullWidth onClick={() => navigate("/admin/users")} disabled={loading}>
                  Cancel
                </Button>
              </div>
            </CardContent></Card>

            {isEdit && (
              <Card className="border-red-200"><CardContent className="p-6">
                <h3 className="font-bold text-red-900 mb-2">Danger Zone</h3>
                <p className="text-sm text-slate-700 mb-4">Soft-delete this account. The user will be disabled immediately.</p>
                <Button type="button" variant="outline" fullWidth onClick={handleDelete} disabled={loading}
                  className="border-red-300 text-red-700 hover:bg-red-50">
                  Delete User
                </Button>
              </CardContent></Card>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
