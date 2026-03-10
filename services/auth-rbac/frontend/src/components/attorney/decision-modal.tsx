import React, { useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, X, Calculator } from 'lucide-react';
import { Button } from '../ui/button';
import { useToast } from '../ui/toast-provider';
import { useNavigate } from 'react-router';

/**
 * Decision Modal
 * Modal for attorney to approve, reject, or escalate a case with reason capture
 */

interface DecisionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (reason?: string) => void;
  decisionType: 'approve' | 'reject' | 'escalate';
  caseNumber: string;
  clientName: string;
}

const REJECTION_REASONS = [
  'Insufficient medical documentation',
  'Missing required exposure evidence',
  'Incomplete client information',
  'Medical causation not established',
  'Outside VCF eligibility window',
  'Duplicate claim detected',
  'Fraudulent documentation suspected',
  'Other (specify below)',
];

const ESCALATION_REASONS = [
  'Complex medical history requires senior review',
  'High-value case needs partner approval',
  'Conflicting documentation requires clarification',
  'Novel legal issue requires consultation',
  'Potential liability concerns',
  'Client complaint or dispute',
  'Other (specify below)',
];

export function DecisionModal({
  isOpen,
  onClose,
  onSubmit,
  decisionType,
  caseNumber,
  clientName,
}: DecisionModalProps) {
  const { addToast } = useToast();
  const [selectedReason, setSelectedReason] = useState('');
  const [customReason, setCustomReason] = useState('');
  const [escalateTo, setEscalateTo] = useState('');

  if (!isOpen) return null;

  const handleSubmit = () => {
    if (decisionType === 'reject' && !selectedReason) {
      addToast({
        variant: 'error',
        title: 'Reason Required',
        message: 'Please select a reason for rejection',
      });
      return;
    }

    if (decisionType === 'escalate' && (!selectedReason || !escalateTo)) {
      addToast({
        variant: 'error',
        title: 'Information Required',
        message: 'Please select a reason and recipient for escalation',
      });
      return;
    }

    const finalReason =
      selectedReason === 'Other (specify below)' ? customReason : selectedReason;

    onSubmit(finalReason);
    
    addToast({
      variant: 'success',
      title: 'Decision Recorded',
      message: `Case has been ${decisionType}d successfully`,
    });
  };

  const getIcon = () => {
    switch (decisionType) {
      case 'approve':
        return <CheckCircle2 className="w-12 h-12 text-green-600" />;
      case 'reject':
        return <XCircle className="w-12 h-12 text-red-600" />;
      case 'escalate':
        return <AlertTriangle className="w-12 h-12 text-yellow-600" />;
    }
  };

  const getTitle = () => {
    switch (decisionType) {
      case 'approve':
        return 'Approve Case for VCF Submission';
      case 'reject':
        return 'Reject Case';
      case 'escalate':
        return 'Escalate Case for Review';
    }
  };

  const getDescription = () => {
    switch (decisionType) {
      case 'approve':
        return 'This case will be approved and prepared for submission to the VCF. Please confirm this decision.';
      case 'reject':
        return 'This case will be rejected and returned to the paralegal with your feedback. Please provide a reason for rejection.';
      case 'escalate':
        return 'This case will be escalated to a senior attorney or partner for additional review. Please provide details.';
    }
  };

  const getReasonOptions = () => {
    if (decisionType === 'reject') return REJECTION_REASONS;
    if (decisionType === 'escalate') return ESCALATION_REASONS;
    return [];
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose}></div>

      {/* Modal */}
      <div className="relative min-h-screen flex items-center justify-center p-4">
        <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl">
          {/* Close Button */}
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-600" />
          </button>

          {/* Header */}
          <div className="p-8 border-b border-slate-200">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">{getIcon()}</div>
              <div className="flex-1">
                <h2 className="text-2xl font-bold text-slate-900 mb-2">{getTitle()}</h2>
                <p className="text-slate-600">{getDescription()}</p>
              </div>
            </div>
          </div>

          {/* Body */}
          <div className="p-8 space-y-6">
            {/* Case Info */}
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-slate-600">Case Number</p>
                  <p className="font-semibold text-slate-900">{caseNumber}</p>
                </div>
                <div>
                  <p className="text-slate-600">Client Name</p>
                  <p className="font-semibold text-slate-900">{clientName}</p>
                </div>
              </div>
            </div>

            {/* Approval Confirmation */}
            {decisionType === 'approve' && (
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <h3 className="font-semibold text-green-900 mb-2">Next Steps</h3>
                <ul className="space-y-2 text-sm text-green-800">
                  <li className="flex items-start gap-2">
                    <span className="text-green-600 mt-0.5">•</span>
                    <span>Case will be marked as "Approved for Submission"</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-green-600 mt-0.5">•</span>
                    <span>Paralegal will be notified to proceed with VCF filing</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-green-600 mt-0.5">•</span>
                    <span>Case will move to "Submission Queue"</span>
                  </li>
                </ul>
              </div>
            )}

            {/* Rejection Reasons */}
            {decisionType === 'reject' && (
              <div>
                <label className="block text-sm font-semibold text-slate-900 mb-3">
                  Reason for Rejection <span className="text-red-500">*</span>
                </label>
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {getReasonOptions().map((reason) => (
                    <label
                      key={reason}
                      className="flex items-start gap-3 p-3 border border-slate-200 rounded-lg cursor-pointer hover:bg-slate-50 transition-colors"
                    >
                      <input
                        type="radio"
                        name="reason"
                        value={reason}
                        checked={selectedReason === reason}
                        onChange={(e) => setSelectedReason(e.target.value)}
                        className="mt-0.5"
                      />
                      <span className="text-sm text-slate-900">{reason}</span>
                    </label>
                  ))}
                </div>

                {selectedReason === 'Other (specify below)' && (
                  <div className="mt-4">
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                      Please specify the reason
                    </label>
                    <textarea
                      value={customReason}
                      onChange={(e) => setCustomReason(e.target.value)}
                      className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
                      rows={4}
                      placeholder="Provide detailed reason for rejection..."
                    />
                  </div>
                )}
              </div>
            )}

            {/* Escalation Details */}
            {decisionType === 'escalate' && (
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-semibold text-slate-900 mb-3">
                    Escalate To <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={escalateTo}
                    onChange={(e) => setEscalateTo(e.target.value)}
                    className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <option value="">Select recipient...</option>
                    <option value="senior_attorney">Senior Attorney - David Wilson</option>
                    <option value="managing_partner">Managing Partner - Jennifer Lee</option>
                    <option value="medical_consultant">Medical Consultant - Dr. Robert Chen</option>
                    <option value="legal_team">Legal Review Team</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-semibold text-slate-900 mb-3">
                    Reason for Escalation <span className="text-red-500">*</span>
                  </label>
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {getReasonOptions().map((reason) => (
                      <label
                        key={reason}
                        className="flex items-start gap-3 p-3 border border-slate-200 rounded-lg cursor-pointer hover:bg-slate-50 transition-colors"
                      >
                        <input
                          type="radio"
                          name="reason"
                          value={reason}
                          checked={selectedReason === reason}
                          onChange={(e) => setSelectedReason(e.target.value)}
                          className="mt-0.5"
                        />
                        <span className="text-sm text-slate-900">{reason}</span>
                      </label>
                    ))}
                  </div>

                  {selectedReason === 'Other (specify below)' && (
                    <div className="mt-4">
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Please provide details
                      </label>
                      <textarea
                        value={customReason}
                        onChange={(e) => setCustomReason(e.target.value)}
                        className="w-full px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
                        rows={4}
                        placeholder="Provide detailed reason for escalation..."
                      />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-8 border-t border-slate-200 bg-slate-50 rounded-b-2xl">
            <div className="flex items-center justify-end gap-3">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleSubmit}
                className={
                  decisionType === 'approve'
                    ? 'bg-green-600 hover:bg-green-700'
                    : decisionType === 'reject'
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-yellow-600 hover:bg-yellow-700'
                }
              >
                {decisionType === 'approve' && 'Confirm Approval'}
                {decisionType === 'reject' && 'Confirm Rejection'}
                {decisionType === 'escalate' && 'Confirm Escalation'}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}