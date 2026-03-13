import React, { useState } from 'react';
import { Save, Mail, DollarSign, Calendar, Bell, FileText, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { useToast } from '../ui/toast-provider';

/**
 * System Settings
 * Configure notification templates, fee defaults, and deadline configurations
 */

type SettingsTab = 'notifications' | 'fees' | 'deadlines' | 'general';

export function SystemSettings() {
  const { addToast } = useToast();
  const [activeTab, setActiveTab] = useState<SettingsTab>('notifications');
  const [hasChanges, setHasChanges] = useState(false);

  // Notification Template Settings
  const [emailTemplates, setEmailTemplates] = useState({
    welcomeEmail: {
      subject: 'Welcome to SimpleTort - Your VCF Case',
      body: 'Dear {{client_name}},\n\nWelcome to SimpleTort. We have received your VCF case and will begin processing immediately.\n\nYour case number is: {{case_number}}\n\nBest regards,\nSimpleTort Team',
    },
    caseApprovedEmail: {
      subject: 'VCF Case Approved - {{case_number}}',
      body: 'Dear {{client_name}},\n\nGreat news! Your VCF case {{case_number}} has been approved and submitted to the VCF.\n\nNext steps will be communicated shortly.\n\nBest regards,\nSimpleTort Team',
    },
    documentRequestEmail: {
      subject: 'Document Request - {{case_number}}',
      body: 'Dear {{client_name}},\n\nWe need additional documents for case {{case_number}}:\n\n{{document_list}}\n\nPlease upload at your earliest convenience.\n\nBest regards,\nSimpleTort Team',
    },
  });

  // Fee Settings
  const [feeSettings, setFeeSettings] = useState({
    attorneyFeePercentage: 33.33,
    referralFeePercentage: 10.0,
    defaultExpenses: [
      { name: 'Medical Records', amount: 150 },
      { name: 'Expert Witness', amount: 2500 },
      { name: 'Filing Fees', amount: 400 },
    ],
    taxWithholdingPercentage: 0,
  });

  // Deadline Settings
  const [deadlineSettings, setDeadlineSettings] = useState({
    urgentThresholdDays: 7,
    highPriorityThresholdDays: 30,
    mediumPriorityThresholdDays: 60,
    reminderDaysBefore: [30, 14, 7, 3, 1],
    autoEscalateDays: 3,
  });

  // General Settings
  const [generalSettings, setGeneralSettings] = useState({
    companyName: 'SimpleTort',
    companyEmail: 'info@simpletort.com',
    companyPhone: '(555) 123-4567',
    timezone: 'America/New_York',
    dateFormat: 'MM/DD/YYYY',
    currency: 'USD',
  });

  const handleSave = () => {
    // Simulate save
    addToast({
      message: 'Settings saved successfully',
      type: 'success',
    });
    setHasChanges(false);
  };

  const tabs = [
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'fees', label: 'Fees & Expenses', icon: DollarSign },
    { id: 'deadlines', label: 'Deadlines', icon: Calendar },
    { id: 'general', label: 'General', icon: FileText },
  ];

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">System Settings</h2>
          <p className="text-slate-600 mt-1">
            Configure notification templates, fee defaults, and system preferences
          </p>
        </div>
        {hasChanges && (
          <Button
            variant="primary"
            leftIcon={<Save className="w-4 h-4" />}
            onClick={handleSave}
          >
            Save Changes
          </Button>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200 mb-6">
        <div className="flex gap-1">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as SettingsTab)}
                className={`
                  flex items-center gap-2 px-4 py-3 border-b-2 transition-colors
                  ${
                    activeTab === tab.id
                      ? 'border-blue-600 text-blue-600 bg-blue-50'
                      : 'border-transparent text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                  }
                `}
              >
                <Icon className="w-4 h-4" />
                <span className="font-medium text-sm">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content */}
      <div>
        {/* Notifications Tab */}
        {activeTab === 'notifications' && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Mail className="w-5 h-5 text-blue-600" />
                  <h3 className="text-lg font-bold text-slate-900">Email Templates</h3>
                </div>
                <p className="text-sm text-slate-600 mb-6">
                  Customize email templates sent to clients. Use variables like{' '}
                  <code className="bg-slate-100 px-2 py-1 rounded text-xs">
                    {'{{client_name}}'}
                  </code>
                  ,{' '}
                  <code className="bg-slate-100 px-2 py-1 rounded text-xs">
                    {'{{case_number}}'}
                  </code>
                </p>

                <div className="space-y-6">
                  {Object.entries(emailTemplates).map(([key, template]) => (
                    <div key={key} className="border border-slate-200 rounded-lg p-4">
                      <h4 className="font-semibold text-slate-900 mb-3 capitalize">
                        {key.replace(/([A-Z])/g, ' $1').trim()}
                      </h4>
                      <div className="space-y-3">
                        <div>
                          <label className="block text-sm font-medium text-slate-700 mb-2">
                            Subject Line
                          </label>
                          <input
                            type="text"
                            value={template.subject}
                            onChange={(e) => {
                              setEmailTemplates({
                                ...emailTemplates,
                                [key]: { ...template, subject: e.target.value },
                              });
                              setHasChanges(true);
                            }}
                            className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-slate-700 mb-2">
                            Email Body
                          </label>
                          <textarea
                            rows={6}
                            value={template.body}
                            onChange={(e) => {
                              setEmailTemplates({
                                ...emailTemplates,
                                [key]: { ...template, body: e.target.value },
                              });
                              setHasChanges(true);
                            }}
                            className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Fees Tab */}
        {activeTab === 'fees' && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <DollarSign className="w-5 h-5 text-green-600" />
                  <h3 className="text-lg font-bold text-slate-900">Fee Structure</h3>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Attorney Fee (%)
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        step="0.01"
                        value={feeSettings.attorneyFeePercentage}
                        onChange={(e) => {
                          setFeeSettings({
                            ...feeSettings,
                            attorneyFeePercentage: parseFloat(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        %
                      </span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Referral Fee (%)
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        step="0.01"
                        value={feeSettings.referralFeePercentage}
                        onChange={(e) => {
                          setFeeSettings({
                            ...feeSettings,
                            referralFeePercentage: parseFloat(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        %
                      </span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6">
                <h3 className="text-lg font-bold text-slate-900 mb-4">Default Expenses</h3>
                <div className="space-y-3">
                  {feeSettings.defaultExpenses.map((expense, idx) => (
                    <div key={idx} className="flex items-center gap-3">
                      <input
                        type="text"
                        value={expense.name}
                        onChange={(e) => {
                          const newExpenses = [...feeSettings.defaultExpenses];
                          newExpenses[idx].name = e.target.value;
                          setFeeSettings({ ...feeSettings, defaultExpenses: newExpenses });
                          setHasChanges(true);
                        }}
                        className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="Expense name"
                      />
                      <div className="relative w-40">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">
                          $
                        </span>
                        <input
                          type="number"
                          value={expense.amount}
                          onChange={(e) => {
                            const newExpenses = [...feeSettings.defaultExpenses];
                            newExpenses[idx].amount = parseFloat(e.target.value);
                            setFeeSettings({ ...feeSettings, defaultExpenses: newExpenses });
                            setHasChanges(true);
                          }}
                          className="w-full pl-7 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="0.00"
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => {
                    setFeeSettings({
                      ...feeSettings,
                      defaultExpenses: [
                        ...feeSettings.defaultExpenses,
                        { name: '', amount: 0 },
                      ],
                    });
                    setHasChanges(true);
                  }}
                >
                  Add Expense
                </Button>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Deadlines Tab */}
        {activeTab === 'deadlines' && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Calendar className="w-5 h-5 text-orange-600" />
                  <h3 className="text-lg font-bold text-slate-900">Priority Thresholds</h3>
                </div>
                <p className="text-sm text-slate-600 mb-4">
                  Configure how many days before deadline each priority level triggers
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Urgent (Red)
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        value={deadlineSettings.urgentThresholdDays}
                        onChange={(e) => {
                          setDeadlineSettings({
                            ...deadlineSettings,
                            urgentThresholdDays: parseInt(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        days
                      </span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      High Priority (Orange)
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        value={deadlineSettings.highPriorityThresholdDays}
                        onChange={(e) => {
                          setDeadlineSettings({
                            ...deadlineSettings,
                            highPriorityThresholdDays: parseInt(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        days
                      </span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Medium Priority (Yellow)
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        value={deadlineSettings.mediumPriorityThresholdDays}
                        onChange={(e) => {
                          setDeadlineSettings({
                            ...deadlineSettings,
                            mediumPriorityThresholdDays: parseInt(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        days
                      </span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Auto-Escalate After
                    </label>
                    <div className="relative">
                      <input
                        type="number"
                        value={deadlineSettings.autoEscalateDays}
                        onChange={(e) => {
                          setDeadlineSettings({
                            ...deadlineSettings,
                            autoEscalateDays: parseInt(e.target.value),
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500">
                        days
                      </span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6">
                <h3 className="text-lg font-bold text-slate-900 mb-4">Reminder Schedule</h3>
                <p className="text-sm text-slate-600 mb-4">
                  Send automated reminders this many days before deadline
                </p>
                <div className="flex flex-wrap gap-2">
                  {deadlineSettings.reminderDaysBefore.map((days, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input
                        type="number"
                        value={days}
                        onChange={(e) => {
                          const newReminders = [...deadlineSettings.reminderDaysBefore];
                          newReminders[idx] = parseInt(e.target.value);
                          setDeadlineSettings({
                            ...deadlineSettings,
                            reminderDaysBefore: newReminders,
                          });
                          setHasChanges(true);
                        }}
                        className="w-20 px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <span className="text-sm text-slate-600">days</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* General Tab */}
        {activeTab === 'general' && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <FileText className="w-5 h-5 text-slate-600" />
                  <h3 className="text-lg font-bold text-slate-900">Company Information</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Company Name
                    </label>
                    <input
                      type="text"
                      value={generalSettings.companyName}
                      onChange={(e) => {
                        setGeneralSettings({
                          ...generalSettings,
                          companyName: e.target.value,
                        });
                        setHasChanges(true);
                      }}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Company Email
                      </label>
                      <input
                        type="email"
                        value={generalSettings.companyEmail}
                        onChange={(e) => {
                          setGeneralSettings({
                            ...generalSettings,
                            companyEmail: e.target.value,
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Company Phone
                      </label>
                      <input
                        type="tel"
                        value={generalSettings.companyPhone}
                        onChange={(e) => {
                          setGeneralSettings({
                            ...generalSettings,
                            companyPhone: e.target.value,
                          });
                          setHasChanges(true);
                        }}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6">
                <h3 className="text-lg font-bold text-slate-900 mb-4">Regional Settings</h3>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Timezone
                    </label>
                    <select
                      value={generalSettings.timezone}
                      onChange={(e) => {
                        setGeneralSettings({
                          ...generalSettings,
                          timezone: e.target.value,
                        });
                        setHasChanges(true);
                      }}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="America/New_York">Eastern Time</option>
                      <option value="America/Chicago">Central Time</option>
                      <option value="America/Denver">Mountain Time</option>
                      <option value="America/Los_Angeles">Pacific Time</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Date Format
                    </label>
                    <select
                      value={generalSettings.dateFormat}
                      onChange={(e) => {
                        setGeneralSettings({
                          ...generalSettings,
                          dateFormat: e.target.value,
                        });
                        setHasChanges(true);
                      }}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                      <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                      <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Currency
                    </label>
                    <select
                      value={generalSettings.currency}
                      onChange={(e) => {
                        setGeneralSettings({
                          ...generalSettings,
                          currency: e.target.value,
                        });
                        setHasChanges(true);
                      }}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="USD">USD ($)</option>
                      <option value="EUR">EUR (€)</option>
                      <option value="GBP">GBP (£)</option>
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
