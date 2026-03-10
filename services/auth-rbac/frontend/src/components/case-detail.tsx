import React, { useState } from 'react';
import { useParams, Link } from 'react-router';
import { 
  ArrowLeft, 
  User, 
  Calendar, 
  FileCheck, 
  MessageSquare, 
  Send,
  CheckCircle,
  AlertCircle
} from 'lucide-react';
import { mockCases } from '../mock-data';
import { AISummaryPanel } from './ai-summary-panel';
import { DeadlineIndicator } from './deadline-indicator';
import { DocumentChecklist } from './document-checklist';
import { CommunicationLog } from './communication-log';
import { cn } from '../lib/utils';

export function CaseDetail() {
  const { caseId } = useParams();
  const [activeTab, setActiveTab] = useState<'overview' | 'documents' | 'communications'>('overview');
  
  const caseData = mockCases.find(c => c.id === caseId);

  if (!caseData) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-slate-400 mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-slate-900 mb-2">Case Not Found</h2>
          <p className="text-slate-600 mb-4">The case you're looking for doesn't exist.</p>
          <Link
            to="/"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Cases
          </Link>
        </div>
      </div>
    );
  }

  const getStatusColor = (status: typeof caseData.status) => {
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

  const completedDocs = caseData.documents.filter(d => d.status === 'Complete').length;
  const totalDocs = caseData.documents.length;
  const docCompletionPercentage = Math.round((completedDocs / totalDocs) * 100);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-slate-700" />
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-slate-900">{caseData.clientName}</h1>
            <p className="text-slate-600 mt-1">{caseData.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={cn(
            'px-3 py-1.5 text-sm font-medium rounded-lg border',
            caseData.caseType === 'WTC' ? 'bg-blue-100 text-blue-800 border-blue-300' : 'bg-purple-100 text-purple-800 border-purple-300'
          )}>
            {caseData.caseType} Case
          </span>
          <span className={cn(
            'px-3 py-1.5 text-sm font-medium rounded-lg border',
            getStatusColor(caseData.status)
          )}>
            {caseData.status}
          </span>
        </div>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm text-slate-600">Medical Score</p>
            <User className="w-5 h-5 text-blue-600" />
          </div>
          <p className="text-3xl font-bold text-blue-600">{caseData.medicalScore}%</p>
          <div className="mt-2 w-full bg-slate-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full"
              style={{ width: `${caseData.medicalScore}%` }}
            />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm text-slate-600">AI Confidence</p>
            <CheckCircle className="w-5 h-5 text-purple-600" />
          </div>
          <p className="text-3xl font-bold text-purple-600">{caseData.medicalConfidence}%</p>
          <div className="mt-2 w-full bg-slate-200 rounded-full h-2">
            <div
              className="bg-purple-600 h-2 rounded-full"
              style={{ width: `${caseData.medicalConfidence}%` }}
            />
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm text-slate-600">Document Progress</p>
            <FileCheck className="w-5 h-5 text-green-600" />
          </div>
          <p className="text-3xl font-bold text-green-600">{docCompletionPercentage}%</p>
          <p className="text-sm text-slate-600 mt-1">{completedDocs}/{totalDocs} complete</p>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm text-slate-600">Assigned To</p>
            <User className="w-5 h-5 text-slate-600" />
          </div>
          <p className="text-lg font-medium text-slate-900">{caseData.assignedTo}</p>
          <p className="text-xs text-slate-600 mt-1">
            Updated: {new Date(caseData.lastUpdated).toLocaleDateString('en-US', { 
              month: 'short', 
              day: 'numeric' 
            })}
          </p>
        </div>
      </div>

      {/* Deadlines */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <h2 className="text-lg font-medium text-slate-900 mb-3 flex items-center gap-2">
          <Calendar className="w-5 h-5 text-slate-700" />
          Deadlines
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {caseData.deadlines.map((deadline, index) => (
            <DeadlineIndicator
              key={index}
              status={deadline.status}
              type={deadline.type}
              date={deadline.date}
              daysRemaining={deadline.daysRemaining}
            />
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="border-b border-slate-200">
          <div className="flex">
            <button
              onClick={() => setActiveTab('overview')}
              className={cn(
                'px-6 py-3 text-sm font-medium border-b-2 transition-colors',
                activeTab === 'overview'
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-slate-600 hover:text-slate-900'
              )}
            >
              Overview & AI Analysis
            </button>
            <button
              onClick={() => setActiveTab('documents')}
              className={cn(
                'px-6 py-3 text-sm font-medium border-b-2 transition-colors',
                activeTab === 'documents'
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-slate-600 hover:text-slate-900'
              )}
            >
              Documents ({completedDocs}/{totalDocs})
            </button>
            <button
              onClick={() => setActiveTab('communications')}
              className={cn(
                'px-6 py-3 text-sm font-medium border-b-2 transition-colors',
                activeTab === 'communications'
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-slate-600 hover:text-slate-900'
              )}
            >
              Communications ({caseData.communications.length})
            </button>
          </div>
        </div>

        <div className="p-6">
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Case Information */}
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
                <h3 className="font-medium text-slate-900 mb-3">Case Information</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs text-slate-600 mb-1">Case ID</p>
                    <p className="text-sm font-medium text-slate-900">{caseData.id}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-600 mb-1">Case Type</p>
                    <p className="text-sm font-medium text-slate-900">{caseData.caseType}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-600 mb-1">Created Date</p>
                    <p className="text-sm font-medium text-slate-900">
                      {new Date(caseData.createdDate).toLocaleDateString('en-US', { 
                        month: 'short', 
                        day: 'numeric',
                        year: 'numeric'
                      })}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-600 mb-1">Last Updated</p>
                    <p className="text-sm font-medium text-slate-900">
                      {new Date(caseData.lastUpdated).toLocaleDateString('en-US', { 
                        month: 'short', 
                        day: 'numeric',
                        year: 'numeric'
                      })}
                    </p>
                  </div>
                </div>
              </div>

              {/* AI Summary Panel */}
              <AISummaryPanel summary={caseData.aiSummary} />
            </div>
          )}

          {activeTab === 'documents' && (
            <DocumentChecklist documents={caseData.documents} />
          )}

          {activeTab === 'communications' && (
            <CommunicationLog communications={caseData.communications} />
          )}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-medium text-slate-900">Ready to proceed?</h3>
            <p className="text-sm text-slate-600 mt-1">
              Review all information before submitting the case
            </p>
          </div>
          <div className="flex gap-3">
            <button className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg hover:bg-slate-50 transition-colors">
              Save Draft
            </button>
            <button 
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={docCompletionPercentage < 100}
            >
              <Send className="w-4 h-4" />
              Submit for Review
            </button>
          </div>
        </div>
        {docCompletionPercentage < 100 && (
          <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
            <p className="text-sm text-amber-800">
              <strong>Note:</strong> Complete all required documents before submitting for review
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
