import React, { useState } from 'react';
import { Link } from 'react-router';
import { 
  Search, 
  Filter, 
  ChevronDown, 
  ArrowUpDown, 
  FileText, 
  TrendingUp,
  AlertCircle,
  User
} from 'lucide-react';
import { mockCases } from '../mock-data';
import { Case } from '../types';
import { DeadlineIndicator } from './deadline-indicator';
import { cn } from '../lib/utils';

export function CaseList() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState<string>('all');
  const [filterCaseType, setFilterCaseType] = useState<string>('all');
  const [filterAssignee, setFilterAssignee] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'date' | 'score' | 'deadline'>('date');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Get unique values for filters
  const uniqueAssignees = Array.from(new Set(mockCases.map(c => c.assignedTo)));

  // Filter and sort cases
  let filteredCases = mockCases.filter(caseItem => {
    const matchesSearch = 
      caseItem.clientName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      caseItem.id.toLowerCase().includes(searchQuery.toLowerCase());
    
    const matchesStatus = filterStatus === 'all' || caseItem.status === filterStatus;
    const matchesCaseType = filterCaseType === 'all' || caseItem.caseType === filterCaseType;
    const matchesAssignee = filterAssignee === 'all' || caseItem.assignedTo === filterAssignee;

    return matchesSearch && matchesStatus && matchesCaseType && matchesAssignee;
  });

  // Sort cases
  filteredCases.sort((a, b) => {
    let comparison = 0;
    
    if (sortBy === 'date') {
      comparison = new Date(a.lastUpdated).getTime() - new Date(b.lastUpdated).getTime();
    } else if (sortBy === 'score') {
      comparison = a.medicalScore - b.medicalScore;
    } else if (sortBy === 'deadline') {
      const aNextDeadline = Math.min(...a.deadlines.map(d => d.daysRemaining));
      const bNextDeadline = Math.min(...b.deadlines.map(d => d.daysRemaining));
      comparison = aNextDeadline - bNextDeadline;
    }

    return sortOrder === 'asc' ? comparison : -comparison;
  });

  const getStatusColor = (status: Case['status']) => {
    switch (status) {
      case 'Active':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'Pending Review':
        return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'Under Review':
        return 'bg-blue-100 text-blue-800 border-blue-300';
      case 'Submitted':
        return 'bg-purple-100 text-purple-800 border-purple-300';
      case 'Approved':
        return 'bg-emerald-100 text-emerald-800 border-emerald-300';
      default:
        return 'bg-slate-100 text-slate-800 border-slate-300';
    }
  };

  const getMostUrgentDeadline = (deadlines: Case['deadlines']) => {
    return deadlines.reduce((prev, current) => 
      current.daysRemaining < prev.daysRemaining ? current : prev
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Case Management</h1>
        <p className="text-slate-600 mt-1">Manage and track WTC/VCF cases</p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Total Cases</p>
              <p className="text-2xl font-bold text-slate-900">{mockCases.length}</p>
            </div>
            <FileText className="w-8 h-8 text-blue-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Active</p>
              <p className="text-2xl font-bold text-green-600">
                {mockCases.filter(c => c.status === 'Active').length}
              </p>
            </div>
            <TrendingUp className="w-8 h-8 text-green-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Pending Review</p>
              <p className="text-2xl font-bold text-yellow-600">
                {mockCases.filter(c => c.status === 'Pending Review').length}
              </p>
            </div>
            <AlertCircle className="w-8 h-8 text-yellow-600" />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600">Urgent Deadlines</p>
              <p className="text-2xl font-bold text-red-600">
                {mockCases.filter(c => 
                  c.deadlines.some(d => d.status === 'critical')
                ).length}
              </p>
            </div>
            <AlertCircle className="w-8 h-8 text-red-600" />
          </div>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Search */}
          <div className="lg:col-span-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                placeholder="Search by name or case ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Filters */}
          <div className="lg:col-span-6 grid grid-cols-3 gap-3">
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            >
              <option value="all">All Statuses</option>
              <option value="Active">Active</option>
              <option value="Pending Review">Pending Review</option>
              <option value="Under Review">Under Review</option>
              <option value="Submitted">Submitted</option>
              <option value="Approved">Approved</option>
            </select>

            <select
              value={filterCaseType}
              onChange={(e) => setFilterCaseType(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            >
              <option value="all">All Types</option>
              <option value="WTC">WTC</option>
              <option value="VCF">VCF</option>
            </select>

            <select
              value={filterAssignee}
              onChange={(e) => setFilterAssignee(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            >
              <option value="all">All Assignees</option>
              {uniqueAssignees.map(assignee => (
                <option key={assignee} value={assignee}>{assignee}</option>
              ))}
            </select>
          </div>

          {/* Sort */}
          <div className="lg:col-span-2">
            <select
              value={`${sortBy}-${sortOrder}`}
              onChange={(e) => {
                const [newSortBy, newSortOrder] = e.target.value.split('-') as [typeof sortBy, typeof sortOrder];
                setSortBy(newSortBy);
                setSortOrder(newSortOrder);
              }}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            >
              <option value="date-desc">Latest First</option>
              <option value="date-asc">Oldest First</option>
              <option value="score-desc">Score: High to Low</option>
              <option value="score-asc">Score: Low to High</option>
              <option value="deadline-asc">Deadline: Urgent First</option>
              <option value="deadline-desc">Deadline: Latest First</option>
            </select>
          </div>
        </div>
      </div>

      {/* Cases List */}
      <div className="space-y-3">
        {filteredCases.length === 0 ? (
          <div className="bg-white border border-slate-200 rounded-lg p-8 text-center">
            <FileText className="w-12 h-12 text-slate-400 mx-auto mb-3" />
            <p className="text-slate-600">No cases found matching your filters</p>
          </div>
        ) : (
          filteredCases.map((caseItem) => {
            const urgentDeadline = getMostUrgentDeadline(caseItem.deadlines);
            const completedDocs = caseItem.documents.filter(d => d.status === 'Complete').length;
            const totalDocs = caseItem.documents.length;

            return (
              <Link
                key={caseItem.id}
                to={`/case/${caseItem.id}`}
                className="block bg-white border border-slate-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-md transition-all"
              >
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                  {/* Client Info */}
                  <div className="lg:col-span-3">
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                        <User className="w-5 h-5 text-blue-700" />
                      </div>
                      <div>
                        <h3 className="font-medium text-slate-900">{caseItem.clientName}</h3>
                        <p className="text-sm text-slate-600">{caseItem.id.replace('WTC', 'VCF')}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className={cn(
                            'px-2 py-0.5 text-xs font-medium rounded border',
                            caseItem.caseType === 'VCF' ? 'bg-blue-100 text-blue-800 border-blue-300' : 'bg-purple-100 text-purple-800 border-purple-300'
                          )}>
                            {caseItem.caseType.replace('WTC', 'VCF')}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Status & Score */}
                  <div className="lg:col-span-3">
                    <div className="space-y-2">
                      <div>
                        <p className="text-xs text-slate-600 mb-1">Status</p>
                        <span className={cn(
                          'inline-block px-2 py-1 text-xs font-medium rounded border',
                          getStatusColor(caseItem.status)
                        )}>
                          {caseItem.status}
                        </span>
                      </div>
                      <div>
                        <p className="text-xs text-slate-600 mb-1">Medical Score</p>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-slate-200 rounded-full h-2">
                            <div
                              className={cn(
                                'h-2 rounded-full',
                                caseItem.medicalScore >= 90 ? 'bg-green-600' :
                                caseItem.medicalScore >= 80 ? 'bg-blue-600' :
                                caseItem.medicalScore >= 70 ? 'bg-yellow-600' : 'bg-orange-600'
                              )}
                              style={{ width: `${caseItem.medicalScore}%` }}
                            />
                          </div>
                          <span className="text-sm font-medium text-slate-900 w-8">
                            {caseItem.medicalScore}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Deadline */}
                  <div className="lg:col-span-3">
                    <p className="text-xs text-slate-600 mb-2">Next Deadline</p>
                    <DeadlineIndicator
                      status={urgentDeadline.status}
                      type={urgentDeadline.type}
                      date={urgentDeadline.date}
                      daysRemaining={urgentDeadline.daysRemaining}
                      size="sm"
                    />
                  </div>

                  {/* Documents & Assignee */}
                  <div className="lg:col-span-3">
                    <div className="space-y-2">
                      <div>
                        <p className="text-xs text-slate-600 mb-1">Documents</p>
                        <p className="text-sm text-slate-900">
                          <span className="font-medium">{completedDocs}/{totalDocs}</span> completed
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-600 mb-1">Assigned To</p>
                        <p className="text-sm text-slate-900">{caseItem.assignedTo}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}