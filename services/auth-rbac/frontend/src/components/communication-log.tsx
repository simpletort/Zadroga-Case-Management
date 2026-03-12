import React from 'react';
import { Mail, Phone, FileText, Users, Calendar } from 'lucide-react';
import { Communication } from '../types';
import { cn } from '../lib/utils';

interface CommunicationLogProps {
  communications: Communication[];
}

export function CommunicationLog({ communications }: CommunicationLogProps) {
  const getTypeIcon = (type: Communication['type']) => {
    switch (type) {
      case 'Email':
        return <Mail className="w-4 h-4" />;
      case 'Phone':
        return <Phone className="w-4 h-4" />;
      case 'Meeting':
        return <Users className="w-4 h-4" />;
      case 'Document Request':
        return <FileText className="w-4 h-4" />;
    }
  };

  const getTypeColor = (type: Communication['type']) => {
    switch (type) {
      case 'Email':
        return 'bg-blue-100 text-blue-700';
      case 'Phone':
        return 'bg-green-100 text-green-700';
      case 'Meeting':
        return 'bg-purple-100 text-purple-700';
      case 'Document Request':
        return 'bg-orange-100 text-orange-700';
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffTime = Math.abs(now.getTime() - date.getTime());
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined 
    });
  };

  const sortedComms = [...communications].sort((a, b) => 
    new Date(b.date).getTime() - new Date(a.date).getTime()
  );

  return (
    <div className="space-y-3">
      {sortedComms.length === 0 ? (
        <div className="text-center py-8 text-slate-500">
          <Calendar className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No communications recorded yet</p>
        </div>
      ) : (
        sortedComms.map((comm) => (
          <div
            key={comm.id}
            className="bg-white border border-slate-200 rounded-lg p-4 hover:border-slate-300 transition-colors"
          >
            <div className="flex items-start gap-3">
              <div className={cn(
                'p-2 rounded-lg',
                getTypeColor(comm.type)
              )}>
                {getTypeIcon(comm.type)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div className="flex-1">
                    <h4 className="text-sm font-medium text-slate-900 mb-0.5">
                      {comm.subject}
                    </h4>
                    <p className="text-xs text-slate-600">
                      {comm.contact}
                    </p>
                  </div>
                  <span className="text-xs text-slate-500 whitespace-nowrap">
                    {formatDate(comm.date)}
                  </span>
                </div>
                <p className="text-sm text-slate-700 mt-2">
                  {comm.notes}
                </p>
                <div className="flex items-center gap-2 mt-2">
                  <span className={cn(
                    'px-2 py-0.5 text-xs font-medium rounded',
                    getTypeColor(comm.type)
                  )}>
                    {comm.type}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
