import React, { useState, useEffect, useCallback } from "react";
import { Search, Filter, RefreshCw, Shield, User, FileText, Settings, Lock } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { getAuditLog, BACKEND_ROLE_LABELS, type AuditLogEntry, type BackendRole } from "../../lib/api";
import { useToast } from "../ui/toast-provider";

const EVENT_CATEGORY: Record<string, { label: string; color: string; icon: React.FC<{ className?: string }> }> = {
  permission_denied:          { label: "Security",     color: "bg-red-100 text-red-700 border-red-200",    icon: Lock },
  role_change:                { label: "User",         color: "bg-purple-100 text-purple-700 border-purple-200", icon: User },
  user_created:               { label: "User",         color: "bg-blue-100 text-blue-700 border-blue-200",  icon: User },
  user_soft_deleted:          { label: "User",         color: "bg-orange-100 text-orange-700 border-orange-200", icon: User },
  user_deleted_from_auth:     { label: "User",         color: "bg-orange-100 text-orange-700 border-orange-200", icon: User },
};

function categorise(entry: AuditLogEntry) {
  return EVENT_CATEGORY[entry.event_type] ?? { label: "System", color: "bg-slate-100 text-slate-700 border-slate-200", icon: Settings };
}

export function AuditLog() {
  const { addToast } = useToast();
  const [entries,     setEntries]     = useState<AuditLogEntry[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [limitInput,  setLimitInput]  = useState("100");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const { logs } = await getAuditLog({ limit: Number(limitInput) || 100 });
      setEntries(logs);
    } catch (err) {
      addToast({ message: err instanceof Error ? err.message : "Failed to load audit log", type: "error" });
    } finally {
      setLoading(false);
    }
  }, [limitInput, addToast]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const filtered = entries.filter((e) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      e.event_type?.toLowerCase().includes(q) ||
      e.uid?.toLowerCase().includes(q) ||
      e.target_uid?.toLowerCase().includes(q) ||
      e.performed_by?.toLowerCase().includes(q) ||
      JSON.stringify(e).toLowerCase().includes(q)
    );
  });

  const formatTime = (ts: string) => {
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
  };

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Audit Log</h2>
          <p className="text-slate-600 mt-1">Immutable record of all system events (senior partner only)</p>
        </div>
        <Button variant="outline" leftIcon={<RefreshCw className="w-4 h-4" />} onClick={fetchLogs} disabled={loading}>
          Refresh
        </Button>
      </div>

      <Card className="mb-6"><CardContent className="p-4">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input type="text" placeholder="Search event type, UID, user…" value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-600" />
            <select value={limitInput} onChange={(e) => setLimitInput(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
              {[50,100,200].map((n) => <option key={n} value={n}>Last {n}</option>)}
            </select>
          </div>
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
                  {["Timestamp","Event","Category","Actor","Details"].map((h) => (
                    <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-slate-600 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {filtered.map((entry, i) => {
                  const cat = categorise(entry);
                  const Icon = cat.icon;
                  return (
                    <tr key={i} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-4 text-sm text-slate-600 whitespace-nowrap">{formatTime(entry.timestamp)}</td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <Icon className="w-4 h-4 text-slate-400" />
                          <span className="text-sm font-mono text-slate-900">{entry.event_type}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <Badge variant="default" className={`border ${cat.color}`}>{cat.label}</Badge>
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-sm">
                          <p className="font-mono text-slate-700">{entry.uid ?? entry.performed_by ?? "system"}</p>
                          {entry.role && (
                            <p className="text-xs text-slate-500">
                              {BACKEND_ROLE_LABELS[entry.role as BackendRole] ?? entry.role}
                            </p>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-sm text-slate-600 max-w-xs">
                          {entry.event_type === "role_change" && (
                            <span>
                              {entry.old_role} → <strong>{entry.new_role}</strong>
                              {entry.target_user && <span className="text-slate-400"> (target: {entry.target_user})</span>}
                            </span>
                          )}
                          {entry.event_type === "permission_denied" && (
                            <span>Required: <code className="text-xs bg-slate-100 px-1 rounded">{String(entry.required_permission)}</code></span>
                          )}
                          {entry.event_type === "user_soft_deleted" && (
                            <span>Deleted UID: <code className="text-xs bg-slate-100 px-1 rounded">{entry.target_uid}</code></span>
                          )}
                          {!["role_change","permission_denied","user_soft_deleted"].includes(entry.event_type) && (
                            <span className="text-slate-400 italic">—</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {filtered.length === 0 && (
              <div className="text-center py-12">
                <Shield className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                <p className="text-slate-600">No audit events found</p>
              </div>
            )}
          </div>
        )}
      </CardContent></Card>
    </div>
  );
}
