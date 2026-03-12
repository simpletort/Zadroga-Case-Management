import React from 'react';
import { X, Download, Printer } from 'lucide-react';
import { Button } from '../ui/button';

/**
 * Settlement Statement Modal
 * Professional preview of settlement distribution statement
 */

interface SettlementStatementModalProps {
  isOpen: boolean;
  onClose: () => void;
  data: any;
  calculations: {
    attorneyFee: number;
    totalExpenses: number;
    totalLiens: number;
    totalLoans: number;
    totalDeductions: number;
    netToClient: number;
  };
}

export function SettlementStatementModal({
  isOpen,
  onClose,
  data,
  calculations,
}: SettlementStatementModalProps) {
  if (!isOpen) return null;

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(amount);
  };

  const handlePrint = () => {
    window.print();
  };

  const handleDownload = () => {
    // In real app, generate PDF
    alert('PDF download would be triggered here');
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose}></div>

      {/* Modal */}
      <div className="relative min-h-screen flex items-center justify-center p-4">
        <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto">
          {/* Header - No Print */}
          <div className="sticky top-0 bg-white border-b border-slate-200 p-6 print:hidden z-10">
            <div className="flex items-center justify-between">
              <h2 className="text-2xl font-bold text-slate-900">Settlement Statement</h2>
              <div className="flex items-center gap-3">
                <Button
                  variant="outline"
                  leftIcon={<Printer className="w-4 h-4" />}
                  onClick={handlePrint}
                >
                  Print
                </Button>
                <Button
                  variant="outline"
                  leftIcon={<Download className="w-4 h-4" />}
                  onClick={handleDownload}
                >
                  Download PDF
                </Button>
                <button
                  onClick={onClose}
                  className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5 text-slate-600" />
                </button>
              </div>
            </div>
          </div>

          {/* Statement Content - Printable */}
          <div className="p-12 print:p-8" id="settlement-statement">
            {/* Firm Header */}
            <div className="text-center mb-12 pb-8 border-b-2 border-slate-300">
              <h1 className="text-3xl font-bold text-slate-900 mb-2">SimpleTort Law Firm</h1>
              <p className="text-slate-600">123 Legal Street, New York, NY 10001</p>
              <p className="text-slate-600">Phone: (212) 555-0100 | Fax: (212) 555-0101</p>
              <p className="text-slate-600">info@simpletort.com</p>
            </div>

            {/* Document Title */}
            <div className="text-center mb-10">
              <h2 className="text-2xl font-bold text-slate-900 mb-2">
                SETTLEMENT DISTRIBUTION STATEMENT
              </h2>
              <p className="text-slate-600">
                Date: {new Date().toLocaleDateString('en-US', { 
                  year: 'numeric', 
                  month: 'long', 
                  day: 'numeric' 
                })}
              </p>
            </div>

            {/* Case Information */}
            <div className="mb-10 bg-slate-50 border border-slate-200 rounded-lg p-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <p className="text-sm font-semibold text-slate-600 mb-1">CLIENT NAME</p>
                  <p className="text-lg font-bold text-slate-900">{data.clientName}</p>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-600 mb-1">CASE NUMBER</p>
                  <p className="text-lg font-bold text-slate-900">{data.caseNumber}</p>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-600 mb-1">SETTLEMENT TYPE</p>
                  <p className="text-lg font-bold text-slate-900">
                    September 11th Victim Compensation Fund (VCF)
                  </p>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-600 mb-1">SETTLEMENT DATE</p>
                  <p className="text-lg font-bold text-slate-900">
                    {new Date().toLocaleDateString()}
                  </p>
                </div>
              </div>
            </div>

            {/* Settlement Calculation */}
            <div className="mb-10">
              <h3 className="text-xl font-bold text-slate-900 mb-6 pb-2 border-b-2 border-slate-300">
                SETTLEMENT DISTRIBUTION
              </h3>

              {/* Gross Award */}
              <div className="mb-8">
                <table className="w-full">
                  <tbody>
                    <tr className="border-b border-slate-200">
                      <td className="py-4 text-slate-900 font-semibold">
                        GROSS SETTLEMENT AMOUNT
                      </td>
                      <td className="py-4 text-right text-xl font-bold text-green-700">
                        {formatCurrency(data.grossAward)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Deductions */}
              <div className="mb-6">
                <p className="text-sm font-bold text-slate-600 uppercase mb-4">
                  LESS: DEDUCTIONS
                </p>

                {/* Attorney Fee */}
                <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3 pb-3 border-b border-blue-200">
                    <p className="font-bold text-slate-900">Attorney Fee</p>
                    <p className="font-bold text-slate-900">
                      {formatCurrency(calculations.attorneyFee)}
                    </p>
                  </div>
                  <div className="text-sm text-slate-700">
                    <p>Contingency fee: {data.attorneyFeePercentage}% of gross settlement</p>
                    <p className="text-xs text-slate-600 mt-1">
                      ({data.attorneyFeePercentage}% × {formatCurrency(data.grossAward)} = {formatCurrency(calculations.attorneyFee)})
                    </p>
                  </div>
                </div>

                {/* Case Expenses */}
                {data.expenses.length > 0 && (
                  <div className="mb-6 bg-purple-50 border border-purple-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3 pb-3 border-b border-purple-200">
                      <p className="font-bold text-slate-900">Case Expenses</p>
                      <p className="font-bold text-slate-900">
                        {formatCurrency(calculations.totalExpenses)}
                      </p>
                    </div>
                    <div className="space-y-2">
                      {data.expenses.map((expense: any) => (
                        <div key={expense.id} className="flex items-center justify-between text-sm">
                          <div>
                            <p className="text-slate-900">{expense.description}</p>
                            <p className="text-xs text-slate-600">{expense.category}</p>
                          </div>
                          <p className="text-slate-900 font-medium">
                            {formatCurrency(expense.amount)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Liens */}
                {data.liens.length > 0 && (
                  <div className="mb-6 bg-orange-50 border border-orange-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3 pb-3 border-b border-orange-200">
                      <p className="font-bold text-slate-900">Liens</p>
                      <p className="font-bold text-slate-900">
                        {formatCurrency(calculations.totalLiens)}
                      </p>
                    </div>
                    <div className="space-y-2">
                      {data.liens.map((lien: any) => (
                        <div key={lien.id} className="flex items-center justify-between text-sm">
                          <div>
                            <p className="text-slate-900">{lien.holder}</p>
                            <p className="text-xs text-slate-600">
                              {lien.type}
                              {lien.referenceNumber && ` - Ref: ${lien.referenceNumber}`}
                            </p>
                          </div>
                          <p className="text-slate-900 font-medium">
                            {formatCurrency(lien.amount)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Client Advances */}
                {data.clientLoans.length > 0 && (
                  <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3 pb-3 border-b border-yellow-200">
                      <p className="font-bold text-slate-900">Client Advances (Repayment)</p>
                      <p className="font-bold text-slate-900">
                        {formatCurrency(calculations.totalLoans)}
                      </p>
                    </div>
                    <div className="space-y-2">
                      {data.clientLoans.map((loan: any) => (
                        <div key={loan.id} className="flex items-center justify-between text-sm">
                          <div>
                            <p className="text-slate-900">{loan.description}</p>
                            <p className="text-xs text-slate-600">
                              {new Date(loan.date).toLocaleDateString()}
                            </p>
                          </div>
                          <p className="text-slate-900 font-medium">
                            {formatCurrency(loan.amount)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Total Deductions */}
                <div className="bg-slate-100 border-2 border-slate-300 rounded-lg p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-lg font-bold text-slate-900">TOTAL DEDUCTIONS</p>
                    <p className="text-xl font-bold text-red-700">
                      -{formatCurrency(calculations.totalDeductions)}
                    </p>
                  </div>
                </div>
              </div>

              {/* Net to Client */}
              <div className="bg-gradient-to-br from-green-100 to-blue-100 border-4 border-green-500 rounded-lg p-6 mt-8">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-semibold text-slate-600 uppercase mb-1">
                      Net Amount to Client
                    </p>
                    <p className="text-4xl font-bold text-green-700">
                      {formatCurrency(calculations.netToClient)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-slate-600">Percentage of Gross</p>
                    <p className="text-2xl font-bold text-green-700">
                      {((calculations.netToClient / data.grossAward) * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Summary Table */}
            <div className="mb-10 border-2 border-slate-300 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-200">
                    <th className="text-left p-4 font-bold text-slate-900">DESCRIPTION</th>
                    <th className="text-right p-4 font-bold text-slate-900">AMOUNT</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-slate-200">
                    <td className="p-4 text-slate-900">Gross Settlement</td>
                    <td className="p-4 text-right font-semibold text-slate-900">
                      {formatCurrency(data.grossAward)}
                    </td>
                  </tr>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <td className="p-4 text-slate-700 pl-8">Attorney Fee ({data.attorneyFeePercentage}%)</td>
                    <td className="p-4 text-right text-slate-700">
                      ({formatCurrency(calculations.attorneyFee)})
                    </td>
                  </tr>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <td className="p-4 text-slate-700 pl-8">Case Expenses</td>
                    <td className="p-4 text-right text-slate-700">
                      ({formatCurrency(calculations.totalExpenses)})
                    </td>
                  </tr>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <td className="p-4 text-slate-700 pl-8">Liens</td>
                    <td className="p-4 text-right text-slate-700">
                      ({formatCurrency(calculations.totalLiens)})
                    </td>
                  </tr>
                  <tr className="border-b-2 border-slate-300 bg-slate-50">
                    <td className="p-4 text-slate-700 pl-8">Client Advances</td>
                    <td className="p-4 text-right text-slate-700">
                      ({formatCurrency(calculations.totalLoans)})
                    </td>
                  </tr>
                  <tr className="bg-green-100">
                    <td className="p-4 font-bold text-slate-900">NET TO CLIENT</td>
                    <td className="p-4 text-right font-bold text-green-700 text-lg">
                      {formatCurrency(calculations.netToClient)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Acknowledgment */}
            <div className="mb-10 bg-slate-50 border border-slate-200 rounded-lg p-6">
              <h3 className="font-bold text-slate-900 mb-4">CLIENT ACKNOWLEDGMENT</h3>
              <p className="text-sm text-slate-700 mb-6 leading-relaxed">
                I acknowledge that I have reviewed this settlement distribution statement and 
                understand the deductions from my gross settlement amount. I authorize 
                SimpleTort Law Firm to disburse the settlement proceeds as outlined above.
              </p>
              <div className="grid grid-cols-2 gap-8 mt-12">
                <div>
                  <div className="border-b-2 border-slate-400 mb-2"></div>
                  <p className="text-sm text-slate-600">Client Signature</p>
                </div>
                <div>
                  <div className="border-b-2 border-slate-400 mb-2"></div>
                  <p className="text-sm text-slate-600">Date</p>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="text-center text-xs text-slate-500 pt-8 border-t border-slate-200">
              <p className="mb-2">
                This statement is for informational purposes and serves as a record of settlement 
                distribution.
              </p>
              <p>
                © {new Date().getFullYear()} SimpleTort Law Firm. All rights reserved.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Print Styles */}
      <style>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #settlement-statement,
          #settlement-statement * {
            visibility: visible;
          }
          #settlement-statement {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
          .print\\:hidden {
            display: none !important;
          }
        }
      `}</style>
    </div>
  );
}
