import React, { useState } from 'react';
import { X, CheckCircle2, Circle, Calendar, DollarSign, Building2, User } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { useToast } from '../ui/toast-provider';

/**
 * Disbursement Tracking
 * Track actual payment distribution to all parties
 */

interface DisbursementTrackingProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
  calculations: {
    attorneyFee: number;
    totalExpenses: number;
    totalLiens: number;
    totalLoans: number;
    netToClient: number;
  };
}

interface DisbursementItem {
  id: string;
  recipient: string;
  type: 'attorney' | 'lien' | 'client';
  amount: number;
  status: 'pending' | 'scheduled' | 'completed';
  paymentMethod?: string;
  checkNumber?: string;
  confirmationNumber?: string;
  datePaid?: string;
  notes?: string;
}

export function DisbursementTracking({
  isOpen,
  onClose,
  data,
  calculations,
}: DisbursementTrackingProps) {
  const { addToast } = useToast();

  // Initialize disbursement items
  const [disbursements, setDisbursements] = useState<DisbursementItem[]>([
    {
      id: 'attorney',
      recipient: 'SimpleTort Law Firm (Attorney Fee)',
      type: 'attorney',
      amount: calculations.attorneyFee,
      status: 'pending',
    },
    ...data.liens.map((lien: any) => ({
      id: `lien-${lien.id}`,
      recipient: lien.holder,
      type: 'lien' as const,
      amount: lien.amount,
      status: 'pending' as const,
    })),
    {
      id: 'client',
      recipient: data.clientName,
      type: 'client',
      amount: calculations.netToClient,
      status: 'pending',
    },
  ]);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    paymentMethod: '',
    checkNumber: '',
    confirmationNumber: '',
    datePaid: new Date().toISOString().split('T')[0],
    notes: '',
  });

  if (!isOpen) return null;

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  const handleMarkComplete = (id: string) => {
    setEditingId(id);
    const item = disbursements.find((d) => d.id === id);
    if (item) {
      setEditForm({
        paymentMethod: item.paymentMethod || '',
        checkNumber: item.checkNumber || '',
        confirmationNumber: item.confirmationNumber || '',
        datePaid: item.datePaid || new Date().toISOString().split('T')[0],
        notes: item.notes || '',
      });
    }
  };

  const handleSavePayment = () => {
    if (!editForm.paymentMethod) {
      addToast({
        variant: 'error',
        title: 'Payment Method Required',
        message: 'Please select a payment method',
      });
      return;
    }

    setDisbursements((prev) =>
      prev.map((d) =>
        d.id === editingId
          ? {
              ...d,
              status: 'completed',
              paymentMethod: editForm.paymentMethod,
              checkNumber: editForm.checkNumber,
              confirmationNumber: editForm.confirmationNumber,
              datePaid: editForm.datePaid,
              notes: editForm.notes,
            }
          : d
      )
    );

    setEditingId(null);
    addToast({
      variant: 'success',
      title: 'Payment Recorded',
      message: 'Disbursement has been marked as completed',
    });
  };

  const handleMarkPending = (id: string) => {
    setDisbursements((prev) =>
      prev.map((d) =>
        d.id === id
          ? {
              ...d,
              status: 'pending',
              paymentMethod: undefined,
              checkNumber: undefined,
              confirmationNumber: undefined,
              datePaid: undefined,
              notes: undefined,
            }
          : d
      )
    );
  };

  const totalDisbursed = disbursements
    .filter((d) => d.status === 'completed')
    .reduce((sum, d) => sum + d.amount, 0);

  const totalPending = disbursements
    .filter((d) => d.status === 'pending')
    .reduce((sum, d) => sum + d.amount, 0);

  const completedCount = disbursements.filter((d) => d.status === 'completed').length;
  const totalCount = disbursements.length;

  const getRecipientIcon = (type: string) => {
    switch (type) {
      case 'attorney':
        return <Building2 className="w-5 h-5 text-blue-600" />;
      case 'lien':
        return <DollarSign className="w-5 h-5 text-orange-600" />;
      case 'client':
        return <User className="w-5 h-5 text-green-600" />;
      default:
        return <Circle className="w-5 h-5 text-slate-600" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose}></div>

      {/* Modal */}
      <div className="relative min-h-screen flex items-center justify-center p-4">
        <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="sticky top-0 bg-white border-b border-slate-200 p-6 z-10">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-slate-900">Disbursement Tracking</h2>
                <p className="text-sm text-slate-600 mt-1">
                  Track payments to all parties - {completedCount} of {totalCount} completed
                </p>
              </div>
              <button
                onClick={onClose}
                className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-slate-600" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* Summary Stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm text-blue-700 mb-1">Total Settlement</p>
                <p className="text-2xl font-bold text-blue-900">{formatCurrency(data.grossAward)}</p>
              </div>
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <p className="text-sm text-green-700 mb-1">Disbursed</p>
                <p className="text-2xl font-bold text-green-900">{formatCurrency(totalDisbursed)}</p>
              </div>
              <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
                <p className="text-sm text-orange-700 mb-1">Pending</p>
                <p className="text-2xl font-bold text-orange-900">{formatCurrency(totalPending)}</p>
              </div>
            </div>

            {/* Progress Bar */}
            <div className="mb-8">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-semibold text-slate-700">Disbursement Progress</p>
                <p className="text-sm text-slate-600">
                  {Math.round((completedCount / totalCount) * 100)}% Complete
                </p>
              </div>
              <div className="w-full h-3 bg-slate-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-green-500 to-blue-500 transition-all duration-500"
                  style={{ width: `${(completedCount / totalCount) * 100}%` }}
                ></div>
              </div>
            </div>

            {/* Disbursement Items */}
            <div className="space-y-4">
              {disbursements.map((item) => (
                <div
                  key={item.id}
                  className={`border-2 rounded-lg overflow-hidden transition-all ${
                    item.status === 'completed'
                      ? 'border-green-300 bg-green-50'
                      : 'border-slate-200 bg-white'
                  }`}
                >
                  {/* Item Header */}
                  <div className="p-4">
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0 mt-1">
                        {item.status === 'completed' ? (
                          <CheckCircle2 className="w-6 h-6 text-green-600" />
                        ) : (
                          <Circle className="w-6 h-6 text-slate-400" />
                        )}
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-4 mb-2">
                          <div className="flex items-center gap-2">
                            {getRecipientIcon(item.type)}
                            <h3 className="font-semibold text-slate-900">{item.recipient}</h3>
                          </div>
                          <div className="text-right">
                            <p className="text-xl font-bold text-slate-900">
                              {formatCurrency(item.amount)}
                            </p>
                            {item.status === 'completed' ? (
                              <Badge variant="success" className="mt-1">
                                Paid
                              </Badge>
                            ) : (
                              <Badge variant="warning" className="mt-1">
                                Pending
                              </Badge>
                            )}
                          </div>
                        </div>

                        {/* Completed Payment Details */}
                        {item.status === 'completed' && (
                          <div className="mt-4 p-3 bg-white border border-green-200 rounded-lg">
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                              {item.paymentMethod && (
                                <div>
                                  <p className="text-slate-600 text-xs">Payment Method</p>
                                  <p className="font-medium text-slate-900">{item.paymentMethod}</p>
                                </div>
                              )}
                              {item.checkNumber && (
                                <div>
                                  <p className="text-slate-600 text-xs">Check Number</p>
                                  <p className="font-medium text-slate-900">{item.checkNumber}</p>
                                </div>
                              )}
                              {item.confirmationNumber && (
                                <div>
                                  <p className="text-slate-600 text-xs">Confirmation</p>
                                  <p className="font-medium text-slate-900">
                                    {item.confirmationNumber}
                                  </p>
                                </div>
                              )}
                              {item.datePaid && (
                                <div>
                                  <p className="text-slate-600 text-xs">Date Paid</p>
                                  <p className="font-medium text-slate-900">
                                    {new Date(item.datePaid).toLocaleDateString()}
                                  </p>
                                </div>
                              )}
                            </div>
                            {item.notes && (
                              <div className="mt-3 pt-3 border-t border-green-200">
                                <p className="text-xs text-slate-600 mb-1">Notes</p>
                                <p className="text-sm text-slate-900">{item.notes}</p>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Edit Form */}
                        {editingId === item.id && (
                          <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                            <h4 className="font-semibold text-slate-900 mb-4">
                              Record Payment Details
                            </h4>
                            <div className="space-y-4">
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                  <label className="block text-sm font-medium text-slate-700 mb-2">
                                    Payment Method <span className="text-red-500">*</span>
                                  </label>
                                  <select
                                    value={editForm.paymentMethod}
                                    onChange={(e) =>
                                      setEditForm((prev) => ({
                                        ...prev,
                                        paymentMethod: e.target.value,
                                      }))
                                    }
                                    className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  >
                                    <option value="">Select method...</option>
                                    <option value="Check">Check</option>
                                    <option value="Wire Transfer">Wire Transfer</option>
                                    <option value="ACH">ACH Transfer</option>
                                    <option value="Trust Account Transfer">
                                      Trust Account Transfer
                                    </option>
                                  </select>
                                </div>
                                <div>
                                  <label className="block text-sm font-medium text-slate-700 mb-2">
                                    Date Paid
                                  </label>
                                  <input
                                    type="date"
                                    value={editForm.datePaid}
                                    onChange={(e) =>
                                      setEditForm((prev) => ({ ...prev, datePaid: e.target.value }))
                                    }
                                    className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                </div>
                              </div>

                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                  <label className="block text-sm font-medium text-slate-700 mb-2">
                                    Check/Reference Number
                                  </label>
                                  <input
                                    type="text"
                                    value={editForm.checkNumber}
                                    onChange={(e) =>
                                      setEditForm((prev) => ({
                                        ...prev,
                                        checkNumber: e.target.value,
                                      }))
                                    }
                                    placeholder="e.g., CHK-12345"
                                    className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                </div>
                                <div>
                                  <label className="block text-sm font-medium text-slate-700 mb-2">
                                    Confirmation Number
                                  </label>
                                  <input
                                    type="text"
                                    value={editForm.confirmationNumber}
                                    onChange={(e) =>
                                      setEditForm((prev) => ({
                                        ...prev,
                                        confirmationNumber: e.target.value,
                                      }))
                                    }
                                    placeholder="e.g., CONF-67890"
                                    className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                </div>
                              </div>

                              <div>
                                <label className="block text-sm font-medium text-slate-700 mb-2">
                                  Notes (optional)
                                </label>
                                <textarea
                                  value={editForm.notes}
                                  onChange={(e) =>
                                    setEditForm((prev) => ({ ...prev, notes: e.target.value }))
                                  }
                                  rows={3}
                                  placeholder="Additional payment details or notes..."
                                  className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                                />
                              </div>

                              <div className="flex items-center gap-3 pt-2">
                                <Button variant="primary" onClick={handleSavePayment}>
                                  Save Payment
                                </Button>
                                <Button variant="outline" onClick={() => setEditingId(null)}>
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Action Buttons */}
                        {editingId !== item.id && (
                          <div className="mt-4 flex items-center gap-3">
                            {item.status === 'pending' && (
                              <Button
                                variant="primary"
                                size="sm"
                                onClick={() => handleMarkComplete(item.id)}
                              >
                                Mark as Paid
                              </Button>
                            )}
                            {item.status === 'completed' && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleMarkPending(item.id)}
                              >
                                Mark as Pending
                              </Button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Completion Notice */}
            {completedCount === totalCount && (
              <div className="mt-8 bg-gradient-to-r from-green-100 to-blue-100 border-2 border-green-400 rounded-lg p-6 text-center">
                <CheckCircle2 className="w-16 h-16 text-green-600 mx-auto mb-3" />
                <h3 className="text-xl font-bold text-green-900 mb-2">
                  All Disbursements Complete!
                </h3>
                <p className="text-green-800">
                  All payments have been recorded and distributed successfully.
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-slate-200 p-6 bg-slate-50">
            <div className="flex items-center justify-end gap-3">
              <Button variant="outline" onClick={onClose}>
                Close
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
