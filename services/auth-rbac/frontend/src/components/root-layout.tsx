import { Outlet, Link, useLocation, useNavigate } from "react-router";
import { LayoutDashboard, Users, LogOut, UserPlus, Shield, Scale, Calculator } from "lucide-react";
import { useState } from "react";
import { ToastProvider } from "./ui/toast-provider";
import { useAuth } from "../lib/AuthContext";
import { BACKEND_ROLE_LABELS } from "../lib/api";

export function RootLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout, hasPermission } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);

  const handleLogout = async () => {
    setShowUserMenu(false);
    await logout();
    navigate("/login");
  };

  return (
    <ToastProvider>
      <div className="min-h-screen bg-slate-50">
        <nav className="bg-white border-b border-slate-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center gap-8">
                <Link to="/" className="flex items-center gap-3">
                  <div className="border-l border-slate-300 pl-3">
                    <h1 className="font-bold text-slate-900 text-sm">Paralegal Dashboard</h1>
                  </div>
                </Link>
                <div className="flex gap-1">
                  {[
                    { to: "/", label: "Cases", icon: LayoutDashboard, exact: true },
                    { to: "/leads", label: "Leads", icon: UserPlus },
                    { to: "/workload", label: "Workload", icon: Users },
                  ].map(({ to, label, icon: Icon, exact }) => (
                    <Link key={to} to={to}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                        (exact ? location.pathname === to : location.pathname.startsWith(to))
                          ? "bg-blue-100 text-blue-700" : "text-slate-700 hover:bg-slate-100"
                      }`}>
                      <Icon className="w-4 h-4" />{label}
                    </Link>
                  ))}
                </div>
              </div>

              <div className="relative">
                <button onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-100 transition-colors">
                  <div className="text-right">
                    <p className="text-sm font-medium text-slate-900">{user?.displayName}</p>
                    <p className="text-xs text-slate-600">{user ? BACKEND_ROLE_LABELS[user.role] : ""}</p>
                  </div>
                  <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-semibold">
                    {user?.avatarInitials ?? "?"}
                  </div>
                </button>

                {showUserMenu && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setShowUserMenu(false)} />
                    <div className="absolute right-0 mt-2 w-56 bg-white border border-slate-200 rounded-lg shadow-lg z-20">
                      <div className="p-4 border-b border-slate-200">
                        <p className="text-sm font-medium text-slate-900">{user?.displayName}</p>
                        <p className="text-xs text-slate-600">{user?.email}</p>
                      </div>
                      <div className="p-2">
                        {hasPermission("cases.approve") && (
                          <Link to="/attorney/review" onClick={() => setShowUserMenu(false)}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 rounded transition-colors">
                            <Scale className="w-4 h-4" /> Attorney Review
                          </Link>
                        )}
                        <Link to="/settlement-calculator" onClick={() => setShowUserMenu(false)}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 rounded transition-colors">
                          <Calculator className="w-4 h-4" /> Settlement Calculator
                        </Link>
                        {hasPermission("staff.manage") && (
                          <Link to="/admin" onClick={() => setShowUserMenu(false)}
                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 rounded transition-colors">
                            <Shield className="w-4 h-4" /> Administration
                          </Link>
                        )}
                      </div>
                      <div className="p-2 border-t border-slate-200">
                        <button onClick={handleLogout}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-700 hover:bg-red-50 rounded transition-colors">
                          <LogOut className="w-4 h-4" /> Sign out
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  );
}
