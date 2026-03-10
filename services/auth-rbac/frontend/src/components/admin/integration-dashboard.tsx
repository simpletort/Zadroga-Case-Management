import React, { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  Settings,
  Activity,
  Clock,
  Zap,
} from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { useToast } from '../ui/toast-provider';

/**
 * Integration Dashboard
 * Monitor health status of QuickBooks, DocuSign, Twilio integrations
 */

interface Integration {
  id: string;
  name: string;
  description: string;
  status: 'connected' | 'error' | 'warning' | 'disconnected';
  lastSync: string;
  apiVersion: string;
  accountInfo: string;
  metrics: {
    label: string;
    value: string;
  }[];
  actions: string[];
  logo: string;
}

const MOCK_INTEGRATIONS: Integration[] = [
  {
    id: 'quickbooks',
    name: 'QuickBooks Online',
    description: 'Accounting and financial management integration',
    status: 'connected',
    lastSync: '2026-02-25T10:15:00',
    apiVersion: 'v3',
    accountInfo: 'SimpleTort LLC (ID: 1234567890)',
    metrics: [
      { label: 'Invoices Synced', value: '247' },
      { label: 'Last Payment', value: '2 hours ago' },
      { label: 'Sync Frequency', value: 'Every 6 hours' },
    ],
    actions: ['View Settings', 'Sync Now', 'View Logs'],
    logo: '💰',
  },
  {
    id: 'docusign',
    name: 'DocuSign',
    description: 'Electronic signature and document management',
    status: 'warning',
    lastSync: '2026-02-25T09:30:00',
    apiVersion: 'v2.1',
    accountInfo: 'simpletort@example.com',
    metrics: [
      { label: 'Documents Sent', value: '1,432' },
      { label: 'Pending Signatures', value: '23' },
      { label: 'API Rate Limit', value: '87% used' },
    ],
    actions: ['View Settings', 'Refresh Token', 'View Logs'],
    logo: '📝',
  },
  {
    id: 'twilio',
    name: 'Twilio',
    description: 'SMS and voice communication platform',
    status: 'connected',
    lastSync: '2026-02-25T10:25:00',
    apiVersion: '2010-04-01',
    accountInfo: 'Account SID: ACxxx...xxx',
    metrics: [
      { label: 'SMS Sent (Today)', value: '156' },
      { label: 'Balance', value: '$847.32' },
      { label: 'Phone Numbers', value: '3 active' },
    ],
    actions: ['View Settings', 'Add Credits', 'View Logs'],
    logo: '📱',
  },
  {
    id: 'stripe',
    name: 'Stripe',
    description: 'Payment processing for client retainers',
    status: 'error',
    lastSync: '2026-02-24T16:00:00',
    apiVersion: '2023-10-16',
    accountInfo: 'acct_xxx...xxx',
    metrics: [
      { label: 'Last Error', value: 'API key expired' },
      { label: 'Payments Failed', value: '12' },
      { label: 'Revenue (30d)', value: '$0.00' },
    ],
    actions: ['Reconnect', 'Update API Key', 'Contact Support'],
    logo: '💳',
  },
];

export function IntegrationDashboard() {
  const { addToast } = useToast();
  const [integrations, setIntegrations] = useState(MOCK_INTEGRATIONS);
  const [refreshing, setRefreshing] = useState<string | null>(null);

  const getStatusColor = (status: Integration['status']) => {
    switch (status) {
      case 'connected':
        return {
          bg: 'bg-green-100',
          text: 'text-green-700',
          border: 'border-green-200',
          icon: CheckCircle2,
        };
      case 'warning':
        return {
          bg: 'bg-yellow-100',
          text: 'text-yellow-700',
          border: 'border-yellow-200',
          icon: AlertTriangle,
        };
      case 'error':
        return {
          bg: 'bg-red-100',
          text: 'text-red-700',
          border: 'border-red-200',
          icon: XCircle,
        };
      case 'disconnected':
        return {
          bg: 'bg-slate-100',
          text: 'text-slate-700',
          border: 'border-slate-200',
          icon: XCircle,
        };
      default:
        return {
          bg: 'bg-slate-100',
          text: 'text-slate-700',
          border: 'border-slate-200',
          icon: XCircle,
        };
    }
  };

  const formatLastSync = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);

    if (diffMins < 60) return `${diffMins} minutes ago`;
    if (diffHours < 24) return `${diffHours} hours ago`;
    return date.toLocaleDateString();
  };

  const handleRefresh = async (integrationId: string) => {
    setRefreshing(integrationId);
    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 2000));
    setRefreshing(null);
    addToast({
      message: 'Integration refreshed successfully',
      type: 'success',
    });
  };

  const connectedCount = integrations.filter((i) => i.status === 'connected').length;
  const warningCount = integrations.filter((i) => i.status === 'warning').length;
  const errorCount = integrations.filter((i) => i.status === 'error').length;

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-slate-900">Integration Status</h2>
        <p className="text-slate-600 mt-1">
          Monitor and manage third-party service integrations
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Total Integrations</p>
                <p className="text-2xl font-bold text-slate-900">
                  {integrations.length}
                </p>
              </div>
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <Zap className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Connected</p>
                <p className="text-2xl font-bold text-green-600">{connectedCount}</p>
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
                <p className="text-sm text-slate-600">Warnings</p>
                <p className="text-2xl font-bold text-yellow-600">{warningCount}</p>
              </div>
              <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                <AlertTriangle className="w-6 h-6 text-yellow-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Errors</p>
                <p className="text-2xl font-bold text-red-600">{errorCount}</p>
              </div>
              <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
                <XCircle className="w-6 h-6 text-red-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Integration Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {integrations.map((integration) => {
          const statusConfig = getStatusColor(integration.status);
          const StatusIcon = statusConfig.icon;

          return (
            <Card
              key={integration.id}
              className={`border-2 ${statusConfig.border}`}
            >
              <CardContent className="p-6">
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 bg-slate-100 rounded-lg flex items-center justify-center text-2xl">
                      {integration.logo}
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-slate-900">
                        {integration.name}
                      </h3>
                      <p className="text-sm text-slate-600">
                        {integration.description}
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant="default"
                    className={`border ${statusConfig.bg} ${statusConfig.text} ${statusConfig.border}`}
                  >
                    <StatusIcon className="w-3 h-3 mr-1" />
                    {integration.status}
                  </Badge>
                </div>

                {/* Account Info */}
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mb-4">
                  <p className="text-xs text-slate-600 mb-1">Account</p>
                  <p className="text-sm font-medium text-slate-900">
                    {integration.accountInfo}
                  </p>
                  <div className="flex items-center gap-4 mt-2 text-xs text-slate-600">
                    <div className="flex items-center gap-1">
                      <Activity className="w-3 h-3" />
                      API {integration.apiVersion}
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatLastSync(integration.lastSync)}
                    </div>
                  </div>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  {integration.metrics.map((metric, idx) => (
                    <div key={idx} className="text-center">
                      <p className="text-xs text-slate-600 mb-1">{metric.label}</p>
                      <p className="text-sm font-bold text-slate-900">
                        {metric.value}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    leftIcon={<RefreshCw className="w-3 h-3" />}
                    onClick={() => handleRefresh(integration.id)}
                    disabled={refreshing === integration.id}
                  >
                    {refreshing === integration.id ? 'Refreshing...' : 'Refresh'}
                  </Button>
                  <Button variant="outline" size="sm" leftIcon={<Settings className="w-3 h-3" />}>
                    Settings
                  </Button>
                  <Button variant="ghost" size="sm" leftIcon={<ExternalLink className="w-3 h-3" />}>
                    Logs
                  </Button>
                </div>

                {/* Error Message */}
                {integration.status === 'error' && (
                  <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
                    <div className="flex items-start gap-2">
                      <XCircle className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-semibold text-red-900">
                          Connection Error
                        </p>
                        <p className="text-xs text-red-700 mt-1">
                          API authentication failed. Please update your credentials
                          and reconnect.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Warning Message */}
                {integration.status === 'warning' && (
                  <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="w-4 h-4 text-yellow-600 mt-0.5 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-semibold text-yellow-900">
                          Action Required
                        </p>
                        <p className="text-xs text-yellow-700 mt-1">
                          API rate limit approaching threshold. Consider upgrading
                          your plan.
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Activity Log */}
      <Card className="mt-6">
        <CardContent className="p-6">
          <h3 className="text-lg font-bold text-slate-900 mb-4">Recent Activity</h3>
          <div className="space-y-3">
            {[
              {
                time: '10:25 AM',
                integration: 'Twilio',
                message: 'Successfully sent 15 SMS notifications',
                type: 'success',
              },
              {
                time: '10:15 AM',
                integration: 'QuickBooks',
                message: 'Synced 3 new invoices',
                type: 'success',
              },
              {
                time: '09:30 AM',
                integration: 'DocuSign',
                message: 'API rate limit warning - 87% used',
                type: 'warning',
              },
              {
                time: '04:00 PM Yesterday',
                integration: 'Stripe',
                message: 'Connection failed - API key expired',
                type: 'error',
              },
            ].map((activity, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 p-3 bg-slate-50 border border-slate-200 rounded-lg"
              >
                <div
                  className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${
                    activity.type === 'success'
                      ? 'bg-green-500'
                      : activity.type === 'warning'
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-sm text-slate-900">
                      {activity.integration}
                    </span>
                    <span className="text-xs text-slate-500">{activity.time}</span>
                  </div>
                  <p className="text-sm text-slate-700">{activity.message}</p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
