import React from 'react';
import { Outlet, Link, useLocation } from 'react-router';
import { Users, Settings, Plug, FileText, Shield } from 'lucide-react';
import { ToastProvider } from '../ui/toast-provider';

/**
 * Admin Layout
 * Wrapper layout for all administrative pages with navigation
 */

const ADMIN_NAV_ITEMS = [
  { path: '/admin/home', label: 'Overview', icon: Shield },
  { path: '/admin/users', label: 'User Management', icon: Users },
  { path: '/admin/settings', label: 'System Settings', icon: Settings },
  { path: '/admin/integrations', label: 'Integrations', icon: Plug },
  { path: '/admin/audit-log', label: 'Audit Log', icon: FileText },
];

export function AdminLayout() {
  const location = useLocation();

  const isActive = (path: string) => {
    return location.pathname === path || location.pathname.startsWith(path + '/');
  };

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3 py-6">
            <div className="w-10 h-10 bg-gradient-to-br from-purple-600 to-blue-600 rounded-lg flex items-center justify-center">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900">System Administration</h1>
              <p className="text-sm text-slate-600">Manage users, settings, and integrations</p>
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex gap-1">
            {ADMIN_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.path);
              
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`
                    flex items-center gap-2 px-4 py-3 border-b-2 transition-colors
                    ${
                      active
                        ? 'border-blue-600 text-blue-600 bg-blue-50'
                        : 'border-transparent text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
                  <span className="font-medium text-sm">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <ToastProvider>
          <Outlet />
        </ToastProvider>
      </div>
    </div>
  );
}