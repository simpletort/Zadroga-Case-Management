import React, { useState } from 'react';
import { Link } from 'react-router';
import { 
  AlertCircle, 
  Clock, 
  Filter, 
  Search, 
  ChevronDown,
  FileText,
  Calendar,
  TrendingUp,
  User,
  ArrowUpDown
} from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Select } from '../ui/select';
import { Badge } from '../ui/badge';

/**
 * Attorney Review Queue
 * Displays cases awaiting attorney review with priority sorting
 */

interface CaseReview {
  id: string;
  caseNumber: string;
  clientName: string;
  submittedBy: string;
  submittedDate: string;
  priority: 'urgent' | 'high' | 'medium' | 'low';
  daysInQueue: number;
  vcfDeadline: string;
  medicalScore: number;
  medicalConfidence: 'high' | 'medium' | 'low';
  caseType: 'initial' | 'amendment' | 'appeal' | 'deceased';
  estimatedValue: number;
  flags: string[];
}

const MOCK_CASES: CaseReview[] = [
  {
    id: '1',
    caseNumber: 'VCF-2026-1234',
    clientName: 'John Martinez',
    submittedBy: 'Sarah Johnson',
    submittedDate: '2026-02-20',
    priority: 'urgent',
    daysInQueue: 2,
    vcfDeadline: '2026-03-01',
    medicalScore: 92,
    medicalConfidence: 'high',
    caseType: 'initial',
    estimatedValue: 450000,
    flags: ['Missing Document', 'High Value'],
  },
  {
    id: '2',
    caseNumber: 'VCF-2026-1235',
    clientName: 'Maria Rodriguez',
    submittedBy: 'Sarah Johnson',
    submittedDate: '2026-02-19',
    priority: 'high',
    daysInQueue: 3,
    vcfDeadline: '2026-03-15',
    medicalScore: 88,
    medicalConfidence: 'high',
    caseType: 'amendment',
    estimatedValue: 320000,
    flags: [],
  },
  {
    id: '3',
    caseNumber: 'VCF-2026-1236',
    clientName: 'Robert Chen',
    submittedBy: 'Michael Brown',
    submittedDate: '2026-02-18',
    priority: 'medium',
    daysInQueue: 4,
    vcfDeadline: '2026-04-01',
    medicalScore: 75,
    medicalConfidence: 'medium',
    caseType: 'initial',
    estimatedValue: 280000,
    flags: ['Complex Medical History'],
  },
  {
    id: '4',
    caseNumber: 'VCF-2026-1237',
    clientName: 'Patricia Williams',
    submittedBy: 'Emily Davis',
    submittedDate: '2026-02-17',
    priority: 'urgent',
    daysInQueue: 5,
    vcfDeadline: '2026-02-28',
    medicalScore: 65,
    medicalConfidence: 'low',
    caseType: 'deceased',
    estimatedValue: 550000,
    flags: ['Deceased Claim', 'Low Confidence'],
  },
  {
    id: '5',
    caseNumber: 'VCF-2026-1238',
    clientName: 'James Thompson',
    submittedBy: 'Sarah Johnson',
    submittedDate: '2026-02-16',
    priority: 'low',
    daysInQueue: 6,
    vcfDeadline: '2026-05-01',
    medicalScore: 82,
    medicalConfidence: 'high',
    caseType: 'initial',
    estimatedValue: 195000,
    flags: [],
  },
];

export function AttorneyReviewQueue() {
  const [searchTerm, setSearchTerm] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [sortBy, setSortBy] = useState('priority');
  const [cases, setCases] = useState(MOCK_CASES);

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return 'bg-red-100 text-red-700 border-red-200';
      case 'high':
        return 'bg-orange-100 text-orange-700 border-orange-200';
      case 'medium':
        return 'bg-yellow-100 text-yellow-700 border-yellow-200';
      case 'low':
        return 'bg-blue-100 text-blue-700 border-blue-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  const getConfidenceColor = (confidence: string) => {
    switch (confidence) {
      case 'high':
        return 'text-green-700';
      case 'medium':
        return 'text-yellow-700';
      case 'low':
        return 'text-red-700';
      default:
        return 'text-slate-700';
    }
  };

  const getDeadlineColor = (deadline: string) => {
    const daysUntil = Math.floor((new Date(deadline).getTime() - new Date().getTime()) / (1000 * 60 * 60 * 24));
    if (daysUntil <= 7) return 'text-red-600';
    if (daysUntil <= 14) return 'text-yellow-600';
    return 'text-green-600';
  };

  const filteredCases = cases
    .filter((c) => {
      if (searchTerm && !c.clientName.toLowerCase().includes(searchTerm.toLowerCase()) && 
          !c.caseNumber.toLowerCase().includes(searchTerm.toLowerCase())) {
        return false;
      }
      if (priorityFilter !== 'all' && c.priority !== priorityFilter) return false;
      if (typeFilter !== 'all' && c.caseType !== typeFilter) return false;
      return true;
    })
    .sort((a, b) => {
      if (sortBy === 'priority') {
        const priorityOrder = { urgent: 0, high: 1, medium: 2, low: 3 };
        return priorityOrder[a.priority] - priorityOrder[b.priority];
      }
      if (sortBy === 'deadline') {
        return new Date(a.vcfDeadline).getTime() - new Date(b.vcfDeadline).getTime();
      }
      if (sortBy === 'days') {
        return b.daysInQueue - a.daysInQueue;
      }
      if (sortBy === 'score') {
        return b.medicalScore - a.medicalScore;
      }
      return 0;
    });

  const stats = {
    total: cases.length,
    urgent: cases.filter((c) => c.priority === 'urgent').length,
    avgDaysInQueue: Math.round(cases.reduce((sum, c) => sum + c.daysInQueue, 0) / cases.length),
    highValue: cases.filter((c) => c.estimatedValue > 400000).length,
  };

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Review Queue</h1>
        <p className="text-slate-600">Cases submitted by paralegals awaiting attorney review</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Total in Queue</p>
                <p className="text-3xl font-bold text-slate-900 mt-1">{stats.total}</p>
              </div>
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Urgent Cases</p>
                <p className="text-3xl font-bold text-red-600 mt-1">{stats.urgent}</p>
              </div>
              <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
                <AlertCircle className="w-6 h-6 text-red-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Avg. Days in Queue</p>
                <p className="text-3xl font-bold text-slate-900 mt-1">{stats.avgDaysInQueue}</p>
              </div>
              <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                <Clock className="w-6 h-6 text-yellow-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">High Value Cases</p>
                <p className="text-3xl font-bold text-green-600 mt-1">{stats.highValue}</p>
              </div>
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-6 h-6 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card className="mb-6">
        <CardContent className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Search Cases
              </label>
              <Input
                placeholder="Search by name or case #"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="w-4 h-4" />}
                fullWidth
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Priority
              </label>
              <Select
                value={priorityFilter}
                onChange={(e) => setPriorityFilter(e.target.value)}
                options={[
                  { value: 'all', label: 'All Priorities' },
                  { value: 'urgent', label: 'Urgent' },
                  { value: 'high', label: 'High' },
                  { value: 'medium', label: 'Medium' },
                  { value: 'low', label: 'Low' },
                ]}
                fullWidth
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Case Type
              </label>
              <Select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                options={[
                  { value: 'all', label: 'All Types' },
                  { value: 'initial', label: 'Initial Claim' },
                  { value: 'amendment', label: 'Amendment' },
                  { value: 'appeal', label: 'Appeal' },
                  { value: 'deceased', label: 'Deceased' },
                ]}
                fullWidth
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">
                Sort By
              </label>
              <Select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                options={[
                  { value: 'priority', label: 'Priority' },
                  { value: 'deadline', label: 'VCF Deadline' },
                  { value: 'days', label: 'Days in Queue' },
                  { value: 'score', label: 'Medical Score' },
                ]}
                fullWidth
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results Count */}
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-slate-600">
          Showing {filteredCases.length} of {cases.length} cases
        </p>
      </div>

      {/* Cases List */}
      <div className="space-y-4">
        {filteredCases.map((caseItem) => (
          <Card key={caseItem.id} className="hover:shadow-md transition-shadow">
            <CardContent className="p-6">
              <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                {/* Priority Indicator */}
                <div className="flex-shrink-0">
                  <div className={`w-2 h-16 rounded-full ${
                    caseItem.priority === 'urgent' ? 'bg-red-500' :
                    caseItem.priority === 'high' ? 'bg-orange-500' :
                    caseItem.priority === 'medium' ? 'bg-yellow-500' :
                    'bg-blue-500'
                  }`}></div>
                </div>

                {/* Case Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-start gap-3 mb-3">
                    <h3 className="text-lg font-semibold text-slate-900">
                      {caseItem.clientName}
                    </h3>
                    <Badge variant="default" className="text-xs">
                      {caseItem.caseNumber}
                    </Badge>
                    <Badge 
                      variant="default" 
                      className={`text-xs border ${getPriorityColor(caseItem.priority)}`}
                    >
                      {caseItem.priority.toUpperCase()}
                    </Badge>
                    <Badge variant="info" className="text-xs">
                      {caseItem.caseType}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-slate-600 flex items-center gap-1">
                        <User className="w-3.5 h-3.5" />
                        Submitted by
                      </p>
                      <p className="font-medium text-slate-900">{caseItem.submittedBy}</p>
                    </div>

                    <div>
                      <p className="text-slate-600 flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        In Queue
                      </p>
                      <p className="font-medium text-slate-900">{caseItem.daysInQueue} days</p>
                    </div>

                    <div>
                      <p className="text-slate-600 flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        VCF Deadline
                      </p>
                      <p className={`font-medium ${getDeadlineColor(caseItem.vcfDeadline)}`}>
                        {new Date(caseItem.vcfDeadline).toLocaleDateString()}
                      </p>
                    </div>

                    <div>
                      <p className="text-slate-600">Medical Score</p>
                      <p className="font-medium text-slate-900">
                        {caseItem.medicalScore}%{' '}
                        <span className={`text-xs ${getConfidenceColor(caseItem.medicalConfidence)}`}>
                          ({caseItem.medicalConfidence})
                        </span>
                      </p>
                    </div>
                  </div>

                  {/* Flags */}
                  {caseItem.flags.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {caseItem.flags.map((flag, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 px-2 py-1 bg-yellow-50 border border-yellow-200 text-yellow-800 rounded text-xs"
                        >
                          <AlertCircle className="w-3 h-3" />
                          {flag}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Estimated Value */}
                  <div className="mt-3">
                    <p className="text-xs text-slate-600">
                      Est. Value:{' '}
                      <span className="font-semibold text-green-700">
                        ${caseItem.estimatedValue.toLocaleString()}
                      </span>
                    </p>
                  </div>
                </div>

                {/* Action Button */}
                <div className="flex-shrink-0">
                  <Link to={`/attorney/review/${caseItem.id}`}>
                    <Button variant="primary" size="lg">
                      Review Case
                    </Button>
                  </Link>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Empty State */}
      {filteredCases.length === 0 && (
        <Card>
          <CardContent className="p-12 text-center">
            <FileText className="w-16 h-16 text-slate-300 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-slate-900 mb-2">No cases found</h3>
            <p className="text-slate-600">
              Try adjusting your filters or search criteria
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
