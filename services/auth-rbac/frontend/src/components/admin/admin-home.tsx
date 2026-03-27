import React from 'react';
import { useNavigate } from 'react-router';
import { Users, Settings, Plug, FileText, ArrowRight, Shield, CheckCircle2 } from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';

/**
 * Admin Home
 * Landing page for the admin section with quick access to all admin features
 */

const ADMIN_FEATURES = [
  {
    title: 'User Management',
    description: 'Create, edit, and manage system users with role-based permissions',
    icon: Users,
    color: 'blue',
    path: '/admin/users',
    features: ['Add new users', 'Edit roles & permissions', 'Manage user status', 'Track user activity'],
  },
  {
    title: 'System Settings',
    description: 'Configure notification templates, fee defaults, and deadline thresholds',
    icon: Settings,
    color: 'purple',
    path: '/admin/settings',
    features: ['Email templates', 'Fee structure', 'Deadline rules', 'Regional settings'],
  },
  {
    title: 'Integrations',
    description: 'Monitor and manage third-party service integrations',
    icon: Plug,
    color: 'teal',
    path: '/admin/integrations',
    features: ['QuickBooks sync', 'DocuSign status', 'Twilio messaging', 'API health monitoring'],
  },
  {
    title: 'Audit Log',
    description: 'Track all system actions and user activity for compliance',
    icon: FileText,
    color: 'slate',
    path: '/admin/audit-log',
    features: ['Filter by category', 'Search activity', 'Export logs', 'Security tracking'],
  },
];

export function AdminHome() {
  const navigate = useNavigate();

  const getColorClasses = (color: string) => {
    const colors = {
      blue: {
        bg: 'bg-blue-100',
        text: 'text-blue-600',
        border: 'border-blue-200',
        hover: 'hover:border-blue-400',
      },
      purple: {
        bg: 'bg-purple-100',
        text: 'text-purple-600',
        border: 'border-purple-200',
        hover: 'hover:border-purple-400',
      },
      teal: {
        bg: 'bg-teal-100',
        text: 'text-teal-600',
        border: 'border-teal-200',
        hover: 'hover:border-teal-400',
      },
      slate: {
        bg: 'bg-slate-100',
        text: 'text-slate-600',
        border: 'border-slate-200',
        hover: 'hover:border-slate-400',
      },
    };
    return colors[color as keyof typeof colors] || colors.blue;
  };

  return (
    <div>
      {/* Hero Section */}
      <div className="mb-8">
        <div className="flex items-start gap-4">
          <div className="w-16 h-16 bg-gradient-to-br from-purple-600 to-blue-600 rounded-2xl flex items-center justify-center flex-shrink-0">
            <Shield className="w-8 h-8 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="text-3xl font-bold text-slate-900 mb-2">
              System Administration
            </h1>
            <p className="text-lg text-slate-600">
              Manage users, configure system settings, monitor integrations, and track all system activity from one central location.
            </p>
          </div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Total Users</p>
                <p className="text-2xl font-bold text-slate-900">24</p>
              </div>
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <Users className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Active Integrations</p>
                <p className="text-2xl font-bold text-green-600">3/4</p>
              </div>
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <CheckCircle2 className="w-6 h-6 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Audit Events (Today)</p>
                <p className="text-2xl font-bold text-slate-900">847</p>
              </div>
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-purple-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">System Health</p>
                <p className="text-2xl font-bold text-green-600">98%</p>
              </div>
              <div className="w-12 h-12 bg-teal-100 rounded-lg flex items-center justify-center">
                <Shield className="w-6 h-6 text-teal-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Admin Features Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {ADMIN_FEATURES.map((feature) => {
          const Icon = feature.icon;
          const colors = getColorClasses(feature.color);

          return (
            <Card
              key={feature.path}
              className={`border-2 ${colors.border} ${colors.hover} transition-all cursor-pointer group`}
              onClick={() => navigate(feature.path)}
            >
              <CardContent className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-12 h-12 ${colors.bg} rounded-lg flex items-center justify-center`}>
                      <Icon className={`w-6 h-6 ${colors.text}`} />
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-slate-900">{feature.title}</h3>
                      <p className="text-sm text-slate-600">{feature.description}</p>
                    </div>
                  </div>
                  <ArrowRight className="w-5 h-5 text-slate-400 group-hover:text-slate-600 transition-colors" />
                </div>

                <div className="space-y-2">
                  {feature.features.map((item, idx) => (
                    <div key={idx} className="flex items-center gap-2 text-sm text-slate-700">
                      <div className={`w-1.5 h-1.5 rounded-full ${colors.bg}`}></div>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>

                <div className="mt-4 pt-4 border-t border-slate-200">
                  <Button variant="outline" size="sm" fullWidth className="group-hover:bg-slate-50">
                    Open {feature.title}
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Security Notice */}
      <Card className="mt-8 border-blue-200 bg-blue-50">
        <CardContent className="p-6">
          <div className="flex items-start gap-3">
            <Shield className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
            <div>
              <h3 className="font-semibold text-blue-900 mb-1">Security Best Practices</h3>
              <p className="text-sm text-blue-800">
                All administrative actions are logged in the audit log for compliance and security tracking. 
                Ensure you review user permissions regularly and monitor integration health status to maintain 
                system integrity.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
