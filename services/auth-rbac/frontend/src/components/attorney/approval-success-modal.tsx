import React from 'react';
import { CheckCircle2, X, Calculator, ArrowRight } from 'lucide-react';
import { Button } from '../ui/button';
import { useNavigate } from 'react-router';

/**
 * Approval Success Modal
 * Shows after case approval with option to proceed to settlement calculator
 */

interface ApprovalSuccessModalProps {
  isOpen: boolean;
  onClose: () => void;
  caseNumber: string;
  clientName: string;
  caseId: string;
}

export function ApprovalSuccessModal({
  isOpen,
  onClose,
  caseNumber,
  clientName,
  caseId,
}: ApprovalSuccessModalProps) {
  const navigate = useNavigate();

  if (!isOpen) return null;

  const handleGoToSettlement = () => {
    navigate(`/settlement-calculator/${caseId}`);
  };

  const handleBackToQueue = () => {
    navigate('/attorney/review');
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm"></div>

      {/* Modal */}
      <div className="relative min-h-screen flex items-center justify-center p-4">
        <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg">
          {/* Close Button */}
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-600" />
          </button>

          {/* Content */}
          <div className="p-8 text-center">
            {/* Success Icon */}
            <div className="w-20 h-20 bg-gradient-to-br from-green-100 to-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="w-12 h-12 text-green-600" />
            </div>

            {/* Title */}
            <h2 className="text-2xl font-bold text-slate-900 mb-2">Case Approved!</h2>
            <p className="text-slate-600 mb-6">
              {clientName}'s case has been successfully approved for VCF submission.
            </p>

            {/* Case Info */}
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
              <p className="text-sm text-green-700 mb-1">Case Number</p>
              <p className="text-lg font-bold text-green-900">{caseNumber}</p>
            </div>

            {/* Next Steps */}
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 mb-6 text-left">
              <h3 className="font-semibold text-slate-900 mb-3">Next Steps</h3>
              <ul className="space-y-2 text-sm text-slate-700">
                <li className="flex items-start gap-2">
                  <span className="text-green-600 mt-0.5">✓</span>
                  <span>Paralegal has been notified of approval</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-green-600 mt-0.5">✓</span>
                  <span>Case moved to "Approved for Submission" queue</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-blue-600 mt-0.5">→</span>
                  <span>Calculate settlement distribution (recommended)</span>
                </li>
              </ul>
            </div>

            {/* Settlement Calculator CTA */}
            <div className="bg-gradient-to-br from-blue-50 to-purple-50 border-2 border-blue-300 rounded-lg p-5 mb-6">
              <div className="flex items-center justify-center gap-2 mb-2">
                <Calculator className="w-5 h-5 text-blue-600" />
                <h3 className="font-bold text-slate-900">Ready to Calculate Settlement?</h3>
              </div>
              <p className="text-sm text-slate-700 mb-4">
                Proceed to the settlement distribution calculator to determine attorney fees, expenses, liens, and net client distribution.
              </p>
              <Button
                variant="primary"
                onClick={handleGoToSettlement}
                fullWidth
                size="lg"
                rightIcon={<ArrowRight className="w-4 h-4" />}
              >
                Go to Settlement Calculator
              </Button>
            </div>

            {/* Alternative Action */}
            <Button variant="outline" onClick={handleBackToQueue} fullWidth>
              Back to Review Queue
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
