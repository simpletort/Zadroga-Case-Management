import React from 'react';
import { Brain, CheckCircle, AlertTriangle, Info } from 'lucide-react';
import { AISummary } from '../types';
import { cn } from '../lib/utils';

interface AISummaryPanelProps {
  summary: AISummary;
}

export function AISummaryPanel({ summary }: AISummaryPanelProps) {
  const getConfidenceLevel = (confidence: number): { label: string; color: string; bg: string } => {
    if (confidence >= 90) return { label: 'Very High', color: 'text-green-700', bg: 'bg-green-100' };
    if (confidence >= 80) return { label: 'High', color: 'text-blue-700', bg: 'bg-blue-100' };
    if (confidence >= 70) return { label: 'Medium', color: 'text-yellow-700', bg: 'bg-yellow-100' };
    return { label: 'Low', color: 'text-orange-700', bg: 'bg-orange-100' };
  };

  const confidenceLevel = getConfidenceLevel(summary.confidence);

  return (
    <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-purple-600 to-blue-600 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-white" />
            <h3 className="text-white font-medium">AI Medical Analysis</h3>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-purple-100">
              Processed: {new Date(summary.processingDate).toLocaleDateString('en-US', { 
                month: 'short', 
                day: 'numeric' 
              })}
            </span>
          </div>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Confidence Score */}
        <div className={cn('rounded-lg p-3 border', confidenceLevel.bg)}>
          <div className="flex items-center justify-between mb-2">
            <span className={cn('text-sm font-medium', confidenceLevel.color)}>
              Analysis Confidence
            </span>
            <span className={cn('text-2xl font-bold', confidenceLevel.color)}>
              {summary.confidence}%
            </span>
          </div>
          <div className="w-full bg-white/50 rounded-full h-2 mb-1">
            <div
              className={cn(
                'h-2 rounded-full transition-all duration-500',
                summary.confidence >= 90 ? 'bg-green-600' :
                summary.confidence >= 80 ? 'bg-blue-600' :
                summary.confidence >= 70 ? 'bg-yellow-600' : 'bg-orange-600'
              )}
              style={{ width: `${summary.confidence}%` }}
            />
          </div>
          <div className="flex items-center gap-1 mt-2">
            {summary.confidence >= 80 ? (
              <CheckCircle className={cn('w-4 h-4', confidenceLevel.color)} />
            ) : (
              <AlertTriangle className={cn('w-4 h-4', confidenceLevel.color)} />
            )}
            <span className={cn('text-xs', confidenceLevel.color)}>
              {confidenceLevel.label} Confidence
            </span>
          </div>
        </div>

        {/* Summary Text */}
        <div>
          <h4 className="text-sm font-medium text-slate-900 mb-2 flex items-center gap-2">
            <Info className="w-4 h-4 text-slate-600" />
            Executive Summary
          </h4>
          <p className="text-sm text-slate-700 leading-relaxed bg-slate-50 p-3 rounded-lg border border-slate-200">
            {summary.summary}
          </p>
        </div>

        {/* Key Findings */}
        <div>
          <h4 className="text-sm font-medium text-slate-900 mb-2">Key Findings</h4>
          <div className="space-y-2">
            {summary.keyFindings.map((finding, index) => (
              <div key={index} className="flex items-start gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-600 mt-1.5 flex-shrink-0" />
                <span className="text-sm text-slate-700">{finding}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Medical Conditions */}
        <div>
          <h4 className="text-sm font-medium text-slate-900 mb-2">Identified Medical Conditions</h4>
          <div className="flex flex-wrap gap-2">
            {summary.medicalConditions.map((condition, index) => (
              <span
                key={index}
                className="px-3 py-1 bg-purple-100 text-purple-800 text-xs font-medium rounded-full border border-purple-300"
              >
                {condition}
              </span>
            ))}
          </div>
        </div>

        {/* Disclaimer */}
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mt-4">
          <p className="text-xs text-amber-800">
            <strong>Note:</strong> This AI-generated analysis is intended to assist paralegals and should be reviewed by qualified medical and legal professionals. All findings should be verified against source documentation.
          </p>
        </div>
      </div>
    </div>
  );
}
