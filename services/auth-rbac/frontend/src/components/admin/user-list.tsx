import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import { Plus, Search, Edit, Trash2, Mail, Shield, CheckCircle2, XCircle, Filter, RefreshCw } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { listUsers, deleteUser, BACKEND_ROLE_LABELS, type ApiUser, type BackendRole } from "../../lib/api";
import { useToast } from "../ui/toast-provider";

export function UserList() {
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [users,         setUsers]         = useState<ApiUser[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [searchQuery,   setSearchQuery]   = useState("");
  const [roleFilter,    setRoleFilter]    = useState<BackendRole | "all">("all");
  const [statusFilter,  setStatusFilter]  = useState<"all" | "active" | "inactive">("all");

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listUsers({
        role:   roleFilter !== "all" ? roleFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: searchQuery || undefined,
        page_size: 50,
      });
      setUsers(result.users);
    } catch (err) {
      addToast({ message: err instanceof Error ? err.message : "Failed to load users", type: "error" });
    } finally {
      setLoading(false);
    }
  }, [roleFilter, statusFilter, searchQuery, addToast]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleDelete = async (uid: string, name: string) => {
    if (!confirm(`Delete user ${name}? This action soft-deletes the account.`)) return;
    try {
      await deleteUser(uid);
      addToast({ message: `${name} has been removed.`, type: "success" });
      fetchUsers();
    } catch (err) {
      addToast({ message: err instanceof Error ? err.message : "Delete failed", type: "error" });
    }
  };

  const roleBadgeColor = (role: BackendRole) => ({
    senior_partner: "bg-purple-100 text-purple-700 border-purple-200",
    junior_partner: "bg-blue-100 text-blue-700 border-blue-200",
    paralegal:      "bg-teal-100 text-teal-700 border-teal-200",
    admin_staff:    "bg-orange-100 text-orange-700 border-orange-200",
    client:         "bg-slate-100 text-slate-700 border-slate-200",
  }[role] ?? "bg-slate-100 text-slate-700 border-slate-200");

  const statusBadge = (s: string) =>
    s === "active" ? "bg-green-100 text-green-700 border-green-200" : "bg-red-100 text-red-700 border-red-200";

  const counts = {
    total:    users.length,
    active:   users.filter((u) => u.status === "active").length,
    paralegal: users.filter((u) => u.role === "paralegal").length,
    attorney:  users.filter((u) => u.role === "junior_partner").length,
  };

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">User Management</h2>
          <p className="text-slate-600 mt-1">Manage system users, roles, and permissions</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={fetchUsers} disabled={loading}>
            Refresh
          </Button>
          <Button variant="primary" leftIcon={<Plus className="w-4 h-4" />} onClick={() => navigate("/admin/users/new")}>
            Add New User
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: "Total Users",  value: counts.total,    color: "blue" },
          { label: "Active Users", value: counts.active,   color: "green" },
          { label: "Paralegals",   value: counts.paralegal, color: "teal" },
          { label: "Attorneys",    value: counts.attorney,  color: "blue" },
        ].map(({ label, value, color }) => (
          <Card key={label}><CardContent className="p-4">
            <p className="text-sm text-slate-600">{label}</p>
            <p className={`text-2xl font-bold text-${color}-600`}>{value}</p>
          </CardContent></Card>
        ))}
      </div>

      <Card className="mb-6"><CardContent className="p-4">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input type="text" placeholder="Search by name or email…" value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-600" />
            <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as BackendRole | "all")}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="all">All Roles</option>
              {(["senior_partner","junior_partner","paralegal","admin_staff","client"] as BackendRole[]).map((r) => (
                <option key={r} value={r}>{BACKEND_ROLE_LABELS[r]}</option>
              ))}
            </select>
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
            className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </CardContent></Card>

      <Card><CardContent className="p-0">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  {["User","Email","Role","Status","Actions"].map((h) => (
                    <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {users.map((u) => (
                  <tr key={u.uid} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center text-white font-semibold text-sm">
                          {u.display_name.split(" ").map((p) => p[0]).join("").toUpperCase().slice(0, 2)}
                        </div>
                        <div>
                          <p className="font-medium text-slate-900">{u.display_name}</p>
                          <p className="text-xs text-slate-500">{u.uid.slice(0, 8)}…</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <Mail className="w-3 h-3 text-slate-400" />{u.email}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <Badge variant="default" className={`border ${roleBadgeColor(u.role)}`}>
                        {BACKEND_ROLE_LABELS[u.role]}
                      </Badge>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1">
                        {u.status === "active"
                          ? <CheckCircle2 className="w-4 h-4 text-green-500" />
                          : <XCircle     className="w-4 h-4 text-red-500" />}
                        <Badge variant="default" className={`border ${statusBadge(u.status)} capitalize`}>
                          {u.status}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="sm" onClick={() => navigate(`/admin/users/${u.uid}/edit`)}>
                          <Edit className="w-4 h-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(u.uid, u.display_name)}>
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {users.length === 0 && (
              <div className="text-center py-12">
                <Shield className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                <p className="text-slate-600">No users found</p>
              </div>
            )}
          </div>
        )}
      </CardContent></Card>
    </div>
  );
}
