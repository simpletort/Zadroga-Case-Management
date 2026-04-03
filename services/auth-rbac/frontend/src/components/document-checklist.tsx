import React from 'react';
import { CircleCheckBig, Clock, CircleAlert } from 'lucide-react';
import { Document } from '../types';
import { cn } from '../lib/utils';

interface DocumentChecklistProps {
  documents: Document[];
}

export function DocumentChecklist({ documents }: DocumentChecklistProps) {
  const getStatusIcon = (status: Document['status']) => {
    switch (status) {
      case 'Complete':
        return <CircleCheckBig className="w-5 h-5 text-green-600" />;
      case 'Pending':
        return <Clock className="w-5 h-5 text-yellow-600" />;
      case 'Missing':
        return <CircleAlert className="w-5 h-5 text-red-600" />;
    }
  };

  const getStatusColor = (status: Document['status']) => {
    switch (status) {
      case 'Complete':
        return 'text-green-700 bg-green-50';
      case 'Pending':
        return 'text-yellow-700 bg-yellow-50';
      case 'Missing':
        return 'text-red-700 bg-red-50';
    }
  };

  const categorizedDocs = documents.reduce((acc, doc) => {
    if (!acc[doc.category]) {
      acc[doc.category] = [];
    }
    acc[doc.category].push(doc);
    return acc;
  }, {} as Record<string, Document[]>);

  const completedCount = documents.filter(d => d.status === 'Complete').length;
  const totalCount = documents.length;
  const completionPercentage = Math.round((completedCount / totalCount) * 100);

  return (
    <div className="space-y-4">
      {/* Progress Overview */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-blue-900">Document Completion</span>
          <span className="text-sm font-medium text-blue-900">{completedCount}/{totalCount}</span>
        </div>
        <div className="w-full bg-blue-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
            style={{ width: `${completionPercentage}%` }}
          />
        </div>
      </div>

      {/* Document Categories */}
      {Object.entries(categorizedDocs).map(([category, docs]) => (
        <div key={category} className="space-y-2">
          <h4 className="text-sm font-medium text-slate-700">{category}</h4>
          <div className="space-y-2">
            {docs.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-lg hover:border-slate-300 transition-colors"
              >
                <div className="flex items-center gap-3 flex-1">
                  {getStatusIcon(doc.status)}
                  <div className="flex-1">
                    <p className="text-sm font-medium text-slate-900">{doc.name}</p>
                    {doc.uploadedDate && (
                      <p className="text-xs text-slate-500">
                        Uploaded: {new Date(doc.uploadedDate).toLocaleDateString('en-US', { 
                          month: 'short', 
                          day: 'numeric', 
                          year: 'numeric' 
                        })}
                      </p>
                    )}
                  </div>
                </div>
                <span
                  className={cn(
                    'px-2 py-1 text-xs font-medium rounded-full',
                    getStatusColor(doc.status)
                  )}
                >
                  {doc.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
