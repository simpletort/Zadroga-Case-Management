import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router';
import {
  ChevronLeft,
  DollarSign,
  Percent,
  FileText,
  Plus,
  Trash2,
  Receipt,
  Building2,
  Briefcase,
  Calculator,
  Download,
  Eye,
  Save,
  AlertCircle,
} from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { useToast } from '../ui/toast-provider';
import { SettlementStatementModal } from './settlement-statement-modal';
import { DisbursementTracking } from './disbursement-tracking';

/**
 * Settlement Distribution Calculator
 * Calculate and track VCF award distribution with real-time calculations
 */

interface Expense {
  id: string;
  description: string;
  amount: number;
  category: string;
}

interface Lien {
  id: string;
  type: string;
  holder: string;
  amount: number;
  referenceNumber: string;
}

interface ClientLoan {
  id: string;
  date: string;
  description: string;
  amount: number;
}

interface SettlementData {
  caseNumber: string;
  clientName: string;
  grossAward: number;
  attorneyFeePercentage: number;
  expenses: Expense[];
  liens: Lien[];
  clientLoans: ClientLoan[];
}

const EXPENSE_CATEGORIES = [
  'Medical Records',
  'Court Fees',
  'Expert Witness',
  'Investigation',
  'Travel',
  'Postage/Courier',
  'Administrative',
  'Other',
];

const LIEN_TYPES = [
  'Medicare',
  'Medicaid',
  'Medical Provider',
  'Health Insurance',
  'Government',
  'Other',
];

export function SettlementCalculator() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [showStatement, setShowStatement] = useState(false);
  const [showDisbursement, setShowDisbursement] = useState(false);

  // Mock data - in real app, fetch from API
  const [data, setData] = useState<SettlementData>({
    caseNumber: 'VCF-2026-1234',
    clientName: 'John Martinez',
    grossAward: 450000,
    attorneyFeePercentage: 25, // Firm default
    expenses: [
      { id: '1', description: 'Medical Records - Mt. Sinai', amount: 850, category: 'Medical Records' },
      { id: '2', description: 'Expert Medical Review', amount: 2500, category: 'Expert Witness' },
      { id: '3', description: 'Court Filing Fees', amount: 425, category: 'Court Fees' },
    ],
    liens: [
      {
        id: '1',
        type: 'Medicare',
        holder: 'CMS Medicare',
        amount: 15750,
        referenceNumber: 'MED-2026-789456',
      },
    ],
    clientLoans: [
      { id: '1', date: '2025-08-15', description: 'Living expenses advance', amount: 5000 },
      { id: '2', date: '2025-11-20', description: 'Medical treatment advance', amount: 3000 },
    ],
  });

  // Calculations
  const totalExpenses = data.expenses.reduce((sum, exp) => sum + exp.amount, 0);
  const totalLiens = data.liens.reduce((sum, lien) => sum + lien.amount, 0);
  const totalLoans = data.clientLoans.reduce((sum, loan) => sum + loan.amount, 0);
  const attorneyFee = (data.grossAward * data.attorneyFeePercentage) / 100;
  const totalDeductions = attorneyFee + totalExpenses + totalLiens + totalLoans;
  const netToClient = data.grossAward - totalDeductions;

  // Expense Management
  const [newExpense, setNewExpense] = useState({
    description: '',
    amount: '',
    category: EXPENSE_CATEGORIES[0],
  });

  const addExpense = () => {
    if (!newExpense.description || !newExpense.amount) {
      addToast({
        variant: 'error',
        title: 'Missing Information',
        message: 'Please provide description and amount',
      });
      return;
    }

    const expense: Expense = {
      id: Date.now().toString(),
      description: newExpense.description,
      amount: parseFloat(newExpense.amount),
      category: newExpense.category,
    };

    setData((prev) => ({
      ...prev,
      expenses: [...prev.expenses, expense],
    }));

    setNewExpense({ description: '', amount: '', category: EXPENSE_CATEGORIES[0] });

    addToast({
      variant: 'success',
      title: 'Expense Added',
      message: 'Case expense has been added',
    });
  };

  const removeExpense = (id: string) => {
    setData((prev) => ({
      ...prev,
      expenses: prev.expenses.filter((exp) => exp.id !== id),
    }));
  };

  // Lien Management
  const [newLien, setNewLien] = useState({
    type: LIEN_TYPES[0],
    holder: '',
    amount: '',
    referenceNumber: '',
  });

  const addLien = () => {
    if (!newLien.holder || !newLien.amount) {
      addToast({
        variant: 'error',
        title: 'Missing Information',
        message: 'Please provide lien holder and amount',
      });
      return;
    }

    const lien: Lien = {
      id: Date.now().toString(),
      type: newLien.type,
      holder: newLien.holder,
      amount: parseFloat(newLien.amount),
      referenceNumber: newLien.referenceNumber,
    };

    setData((prev) => ({
      ...prev,
      liens: [...prev.liens, lien],
    }));

    setNewLien({ type: LIEN_TYPES[0], holder: '', amount: '', referenceNumber: '' });

    addToast({
      variant: 'success',
      title: 'Lien Added',
      message: 'Lien has been added to settlement',
    });
  };

  const removeLien = (id: string) => {
    setData((prev) => ({
      ...prev,
      liens: prev.liens.filter((lien) => lien.id !== id),
    }));
  };

  // Client Loan Management
  const [newLoan, setNewLoan] = useState({
    date: new Date().toISOString().split('T')[0],
    description: '',
    amount: '',
  });

  const addLoan = () => {
    if (!newLoan.description || !newLoan.amount) {
      addToast({
        variant: 'error',
        title: 'Missing Information',
        message: 'Please provide description and amount',
      });
      return;
    }

    const loan: ClientLoan = {
      id: Date.now().toString(),
      date: newLoan.date,
      description: newLoan.description,
      amount: parseFloat(newLoan.amount),
    };

    setData((prev) => ({
      ...prev,
      clientLoans: [...prev.clientLoans, loan],
    }));

    setNewLoan({ date: new Date().toISOString().split('T')[0], description: '', amount: '' });

    addToast({
      variant: 'success',
      title: 'Loan Added',
      message: 'Client advance has been added',
    });
  };

  const removeLoan = (id: string) => {
    setData((prev) => ({
      ...prev,
      clientLoans: prev.clientLoans.filter((loan) => loan.id !== id),
    }));
  };

  const handleSave = () => {
    // In real app, save to API
    addToast({
      variant: 'success',
      title: 'Settlement Saved',
      message: 'Settlement calculations have been saved',
    });
  };

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount);
  };

  return (
    <div className="max-w-7xl mx-auto pb-12">
      {/* Header */}
      <div className="mb-8">
        <Button
          variant="ghost"
          leftIcon={<ChevronLeft className="w-4 h-4" />}
          onClick={() => navigate(`/case/${caseId}`)}
          className="mb-4"
        >
          Back to Case
        </Button>

        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 mb-2">Settlement Distribution</h1>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="default">{data.caseNumber}</Badge>
              <span className="text-slate-600">{data.clientName}</span>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              leftIcon={<Eye className="w-4 h-4" />}
              onClick={() => setShowStatement(true)}
            >
              Preview Statement
            </Button>
            <Button
              variant="outline"
              leftIcon={<FileText className="w-4 h-4" />}
              onClick={() => setShowDisbursement(true)}
            >
              Track Disbursement
            </Button>
            <Button
              variant="primary"
              leftIcon={<Save className="w-4 h-4" />}
              onClick={handleSave}
            >
              Save Settlement
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content - Calculator Sections */}
        <div className="lg:col-span-2 space-y-6">
          {/* Gross Award */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                  <DollarSign className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Gross VCF Award</h2>
                  <p className="text-sm text-slate-600">Total compensation awarded</p>
                </div>
              </div>

              <div className="max-w-md">
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Award Amount
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 text-lg">
                    $
                  </span>
                  <input
                    type="number"
                    value={data.grossAward}
                    onChange={(e) =>
                      setData((prev) => ({ ...prev, grossAward: parseFloat(e.target.value) || 0 }))
                    }
                    className="w-full pl-8 pr-4 py-3 text-2xl font-bold border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Attorney Fee */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                  <Briefcase className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Attorney Fee</h2>
                  <p className="text-sm text-slate-600">Contingency fee percentage</p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    Fee Percentage
                  </label>
                  <div className="relative">
                    <input
                      type="number"
                      value={data.attorneyFeePercentage}
                      onChange={(e) =>
                        setData((prev) => ({
                          ...prev,
                          attorneyFeePercentage: parseFloat(e.target.value) || 0,
                        }))
                      }
                      min="0"
                      max="100"
                      step="0.1"
                      className="w-full pr-8 pl-4 py-3 text-lg font-semibold border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-500">
                      %
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">Firm default: 25%</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">
                    Fee Amount
                  </label>
                  <div className="py-3 px-4 bg-blue-50 border border-blue-200 rounded-lg">
                    <p className="text-2xl font-bold text-blue-900">{formatCurrency(attorneyFee)}</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Case Expenses */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                  <Receipt className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Case Expenses</h2>
                  <p className="text-sm text-slate-600">Itemized costs advanced by firm</p>
                </div>
              </div>

              {/* Existing Expenses */}
              {data.expenses.length > 0 && (
                <div className="space-y-2 mb-6">
                  {data.expenses.map((expense) => (
                    <div
                      key={expense.id}
                      className="flex items-center justify-between p-4 bg-slate-50 border border-slate-200 rounded-lg"
                    >
                      <div className="flex-1">
                        <p className="font-medium text-slate-900">{expense.description}</p>
                        <p className="text-sm text-slate-600">{expense.category}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        <p className="font-semibold text-slate-900">
                          {formatCurrency(expense.amount)}
                        </p>
                        <button
                          onClick={() => removeExpense(expense.id)}
                          className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                        >
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Add New Expense */}
              <div className="border-t border-slate-200 pt-6">
                <h3 className="font-semibold text-slate-900 mb-4">Add Expense</h3>
                <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                  <div className="md:col-span-5">
                    <input
                      type="text"
                      placeholder="Description"
                      value={newExpense.description}
                      onChange={(e) =>
                        setNewExpense((prev) => ({ ...prev, description: e.target.value }))
                      }
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="md:col-span-3">
                    <select
                      value={newExpense.category}
                      onChange={(e) =>
                        setNewExpense((prev) => ({ ...prev, category: e.target.value }))
                      }
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {EXPENSE_CATEGORIES.map((cat) => (
                        <option key={cat} value={cat}>
                          {cat}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="md:col-span-2">
                    <input
                      type="number"
                      placeholder="Amount"
                      value={newExpense.amount}
                      onChange={(e) =>
                        setNewExpense((prev) => ({ ...prev, amount: e.target.value }))
                      }
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <Button variant="outline" onClick={addExpense} fullWidth>
                      <Plus className="w-4 h-4 mr-2" />
                      Add
                    </Button>
                  </div>
                </div>
              </div>

              {/* Total */}
              <div className="mt-6 pt-6 border-t border-slate-200">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-slate-900">Total Expenses</p>
                  <p className="text-xl font-bold text-purple-600">
                    {formatCurrency(totalExpenses)}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Liens */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-orange-100 rounded-lg flex items-center justify-center">
                  <Building2 className="w-5 h-5 text-orange-600" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Liens</h2>
                  <p className="text-sm text-slate-600">Medicare, medical providers, etc.</p>
                </div>
              </div>

              {/* Existing Liens */}
              {data.liens.length > 0 && (
                <div className="space-y-2 mb-6">
                  {data.liens.map((lien) => (
                    <div
                      key={lien.id}
                      className="p-4 bg-orange-50 border border-orange-200 rounded-lg"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant="default" className="bg-orange-100 text-orange-700">
                              {lien.type}
                            </Badge>
                            <p className="font-medium text-slate-900">{lien.holder}</p>
                          </div>
                          {lien.referenceNumber && (
                            <p className="text-sm text-slate-600">Ref: {lien.referenceNumber}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <p className="font-semibold text-orange-900">
                            {formatCurrency(lien.amount)}
                          </p>
                          <button
                            onClick={() => removeLien(lien.id)}
                            className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                          >
                            <Trash2 className="w-4 h-4 text-red-600" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Add New Lien */}
              <div className="border-t border-slate-200 pt-6">
                <h3 className="font-semibold text-slate-900 mb-4">Add Lien</h3>
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Lien Type
                      </label>
                      <select
                        value={newLien.type}
                        onChange={(e) => setNewLien((prev) => ({ ...prev, type: e.target.value }))}
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        {LIEN_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Lien Holder
                      </label>
                      <input
                        type="text"
                        placeholder="e.g., CMS Medicare"
                        value={newLien.holder}
                        onChange={(e) =>
                          setNewLien((prev) => ({ ...prev, holder: e.target.value }))
                        }
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Amount
                      </label>
                      <input
                        type="number"
                        placeholder="0.00"
                        value={newLien.amount}
                        onChange={(e) =>
                          setNewLien((prev) => ({ ...prev, amount: e.target.value }))
                        }
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-700 mb-2">
                        Reference # (optional)
                      </label>
                      <input
                        type="text"
                        placeholder="Reference number"
                        value={newLien.referenceNumber}
                        onChange={(e) =>
                          setNewLien((prev) => ({ ...prev, referenceNumber: e.target.value }))
                        }
                        className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>
                  <Button variant="outline" onClick={addLien} fullWidth>
                    <Plus className="w-4 h-4 mr-2" />
                    Add Lien
                  </Button>
                </div>
              </div>

              {/* Total */}
              <div className="mt-6 pt-6 border-t border-slate-200">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-slate-900">Total Liens</p>
                  <p className="text-xl font-bold text-orange-600">{formatCurrency(totalLiens)}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Client Loans/Advances */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 bg-yellow-100 rounded-lg flex items-center justify-center">
                  <DollarSign className="w-5 h-5 text-yellow-600" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-slate-900">Client Advances</h2>
                  <p className="text-sm text-slate-600">Loans and advances to be repaid</p>
                </div>
              </div>

              {/* Existing Loans */}
              {data.clientLoans.length > 0 && (
                <div className="space-y-2 mb-6">
                  {data.clientLoans.map((loan) => (
                    <div
                      key={loan.id}
                      className="flex items-center justify-between p-4 bg-yellow-50 border border-yellow-200 rounded-lg"
                    >
                      <div className="flex-1">
                        <p className="font-medium text-slate-900">{loan.description}</p>
                        <p className="text-sm text-slate-600">
                          {new Date(loan.date).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <p className="font-semibold text-yellow-900">
                          {formatCurrency(loan.amount)}
                        </p>
                        <button
                          onClick={() => removeLoan(loan.id)}
                          className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                        >
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Add New Loan */}
              <div className="border-t border-slate-200 pt-6">
                <h3 className="font-semibold text-slate-900 mb-4">Add Client Advance</h3>
                <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                  <div className="md:col-span-3">
                    <input
                      type="date"
                      value={newLoan.date}
                      onChange={(e) => setNewLoan((prev) => ({ ...prev, date: e.target.value }))}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="md:col-span-5">
                    <input
                      type="text"
                      placeholder="Description"
                      value={newLoan.description}
                      onChange={(e) =>
                        setNewLoan((prev) => ({ ...prev, description: e.target.value }))
                      }
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <input
                      type="number"
                      placeholder="Amount"
                      value={newLoan.amount}
                      onChange={(e) => setNewLoan((prev) => ({ ...prev, amount: e.target.value }))}
                      className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <Button variant="outline" onClick={addLoan} fullWidth>
                      <Plus className="w-4 h-4 mr-2" />
                      Add
                    </Button>
                  </div>
                </div>
              </div>

              {/* Total */}
              <div className="mt-6 pt-6 border-t border-slate-200">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-slate-900">Total Client Advances</p>
                  <p className="text-xl font-bold text-yellow-600">{formatCurrency(totalLoans)}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar - Live Calculation Summary */}
        <div className="lg:col-span-1">
          <div className="sticky top-6 space-y-6">
            {/* Settlement Summary */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center gap-3 mb-6">
                  <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-lg flex items-center justify-center">
                    <Calculator className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-lg font-bold text-slate-900">Settlement Summary</h2>
                </div>

                <div className="space-y-4">
                  {/* Gross Award */}
                  <div>
                    <p className="text-sm text-slate-600 mb-1">Gross Award</p>
                    <p className="text-xl font-bold text-green-600">
                      {formatCurrency(data.grossAward)}
                    </p>
                  </div>

                  <div className="border-t border-slate-200 pt-4 space-y-3">
                    <p className="text-xs font-semibold text-slate-500 uppercase">Deductions</p>

                    <div className="flex items-center justify-between">
                      <p className="text-sm text-slate-600">Attorney Fee</p>
                      <p className="text-sm font-semibold text-slate-900">
                        -{formatCurrency(attorneyFee)}
                      </p>
                    </div>

                    <div className="flex items-center justify-between">
                      <p className="text-sm text-slate-600">Case Expenses</p>
                      <p className="text-sm font-semibold text-slate-900">
                        -{formatCurrency(totalExpenses)}
                      </p>
                    </div>

                    <div className="flex items-center justify-between">
                      <p className="text-sm text-slate-600">Liens</p>
                      <p className="text-sm font-semibold text-slate-900">
                        -{formatCurrency(totalLiens)}
                      </p>
                    </div>

                    <div className="flex items-center justify-between">
                      <p className="text-sm text-slate-600">Client Advances</p>
                      <p className="text-sm font-semibold text-slate-900">
                        -{formatCurrency(totalLoans)}
                      </p>
                    </div>
                  </div>

                  <div className="border-t border-slate-200 pt-4">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-sm text-slate-600">Total Deductions</p>
                      <p className="text-sm font-semibold text-red-600">
                        -{formatCurrency(totalDeductions)}
                      </p>
                    </div>
                  </div>

                  {/* Net to Client */}
                  <div className="border-t-2 border-slate-300 pt-4">
                    <p className="text-sm text-slate-600 mb-2">Net to Client</p>
                    <div className="bg-gradient-to-br from-green-50 to-blue-50 border-2 border-green-300 rounded-lg p-4">
                      <p className="text-3xl font-bold text-green-700">
                        {formatCurrency(netToClient)}
                      </p>
                    </div>
                  </div>

                  {/* Warning if negative */}
                  {netToClient < 0 && (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                      <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-red-600 mt-0.5" />
                        <div>
                          <p className="text-sm font-semibold text-red-900">Warning</p>
                          <p className="text-xs text-red-700">
                            Deductions exceed gross award
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Quick Stats */}
            <Card>
              <CardContent className="p-6">
                <h3 className="font-semibold text-slate-900 mb-4">Breakdown</h3>
                <div className="space-y-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Fee Rate</span>
                    <span className="font-semibold">{data.attorneyFeePercentage}%</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Expense Items</span>
                    <span className="font-semibold">{data.expenses.length}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Active Liens</span>
                    <span className="font-semibold">{data.liens.length}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-600">Client Advances</span>
                    <span className="font-semibold">{data.clientLoans.length}</span>
                  </div>
                  <div className="flex items-center justify-between pt-3 border-t border-slate-200">
                    <span className="text-slate-600">Net Percentage</span>
                    <span className="font-semibold text-green-600">
                      {((netToClient / data.grossAward) * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      {/* Modals */}
      {showStatement && (
        <SettlementStatementModal
          isOpen={showStatement}
          onClose={() => setShowStatement(false)}
          data={data}
          calculations={{
            attorneyFee,
            totalExpenses,
            totalLiens,
            totalLoans,
            totalDeductions,
            netToClient,
          }}
        />
      )}

      {showDisbursement && (
        <DisbursementTracking
          isOpen={showDisbursement}
          onClose={() => setShowDisbursement(false)}
          data={data}
          calculations={{
            attorneyFee,
            totalExpenses,
            totalLiens,
            totalLoans,
            netToClient,
          }}
        />
      )}
    </div>
  );
}
