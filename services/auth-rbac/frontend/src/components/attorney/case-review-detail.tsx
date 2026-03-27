import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import {
  ChevronLeft,
  FileText,
  User,
  Calendar,
  AlertCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Download,
  ExternalLink,
  Brain,
  Activity,
  Clock,
  DollarSign,
  Calculator,
} from 'lucide-react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { DecisionModal } from './decision-modal';
import { ApprovalSuccessModal } from './approval-success-modal';

/**
 * Attorney Case Review Detail
 * Comprehensive view for attorneys to review case evidence and make decisions
 */

interface CaseReviewDetail {
  id: string;
  caseNumber: string;
  clientName: string;
  clientDOB: string;
  submittedBy: string;
  submittedDate: string;
  priority: 'urgent' | 'high' | 'medium' | 'low';
  vcfDeadline: string;
  caseType: 'initial' | 'amendment' | 'appeal' | 'deceased';
  estimatedValue: number;
  
  // WTC Exposure
  exposureType: string;
  exposureLocation: string;
  exposureDates: string;
  occupation: string;
  
  // Medical Information
  medicalConditions: string[];
  diagnosisDate: string;
  treatingPhysician: string;
  medicalScore: number;
  medicalConfidence: 'high' | 'medium' | 'low';
  aiSummary: string;
  
  // Documents
  documents: {
    category: string;
    files: { name: string; uploadedDate: string; status: string }[];
  }[];
  
  // Paralegal Notes
  paralegalNotes: string;
  
  // Decision History
  decisionHistory: {
    id: string;
    date: string;
    reviewer: string;
    decision: 'approved' | 'rejected' | 'escalated';
    reason?: string;
  }[];
}

const MOCK_CASE: CaseReviewDetail = {
  id: '1',
  caseNumber: 'VCF-2026-1234',
  clientName: 'John Martinez',
  clientDOB: '1975-06-15',
  submittedBy: 'Sarah Johnson',
  submittedDate: '2026-02-20',
  priority: 'urgent',
  vcfDeadline: '2026-03-01',
  caseType: 'initial',
  estimatedValue: 450000,
  exposureType: 'First Responder (FDNY)',
  exposureLocation: 'Ground Zero, WTC Site',
  exposureDates: '09/11/2001 - 05/15/2002',
  occupation: 'Firefighter',
  medicalConditions: [
    'Chronic Obstructive Pulmonary Disease (COPD)',
    'Asthma',
    'GERD (Gastroesophageal Reflux Disease)',
    'PTSD',
  ],
  diagnosisDate: '2005-03-10',
  treatingPhysician: 'Dr. Sarah Chen, Mt. Sinai Hospital',
  medicalScore: 92,
  medicalConfidence: 'high',
  aiSummary: `This case presents a strong VCF claim based on well-documented exposure and medical evidence. The claimant was a FDNY firefighter who worked at Ground Zero for over 8 months following 9/11. Medical records show clear respiratory conditions consistent with WTC exposure, including COPD and chronic asthma diagnosed in 2005. Treatment history is comprehensive with regular follow-ups at Mt. Sinai WTC Health Program. Confidence level is HIGH due to complete documentation and established causal link between exposure and medical conditions.`,
  documents: [
    {
      category: 'Government ID',
      files: [
        { name: "Driver's License.pdf", uploadedDate: '2026-02-18', status: 'verified' },
      ],
    },
    {
      category: 'Medical Records',
      files: [
        { name: 'Mt_Sinai_Records_2005-2026.pdf', uploadedDate: '2026-02-18', status: 'verified' },
        { name: 'Pulmonary_Function_Tests.pdf', uploadedDate: '2026-02-18', status: 'verified' },
        { name: 'Diagnosis_Letter_Dr_Chen.pdf', uploadedDate: '2026-02-18', status: 'verified' },
      ],
    },
    {
      category: 'Employment Verification',
      files: [
        { name: 'FDNY_Employment_Letter.pdf', uploadedDate: '2026-02-18', status: 'verified' },
        { name: 'FDNY_Assignment_Records.pdf', uploadedDate: '2026-02-18', status: 'verified' },
      ],
    },
    {
      category: 'Exposure Evidence',
      files: [
        { name: 'FDNY_Badge_Photo.jpg', uploadedDate: '2026-02-18', status: 'verified' },
        { name: 'Site_Work_Photos.pdf', uploadedDate: '2026-02-18', status: 'verified' },
      ],
    },
  ],
  paralegalNotes: `Claimant is a highly cooperative FDNY firefighter with excellent documentation. All required documents have been collected and verified. Medical records from Mt. Sinai WTC Health Program are comprehensive and clearly establish causation. FDNY employment and assignment records confirm presence at WTC site. 

Recommend APPROVAL for VCF submission. Case meets all eligibility criteria with high medical qualification score. No red flags identified during review.

Estimated compensation based on similar approved cases and severity of conditions: $450,000.`,
  decisionHistory: [],
};

export function AttorneyCaseReviewDetail() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const [showDecisionModal, setShowDecisionModal] = useState(false);
  const [decisionType, setDecisionType] = useState<'approve' | 'reject' | 'escalate'>('approve');
  const [showApprovalSuccessModal, setShowApprovalSuccessModal] = useState(false);
  
  // In real app, fetch case data by caseId
  const caseData = MOCK_CASE;

  const handleDecision = (type: 'approve' | 'reject' | 'escalate') => {
    setDecisionType(type);
    setShowDecisionModal(true);
  };

  const handleDecisionSubmit = (reason?: string) => {
    // In real app, submit decision to API
    console.log(`Decision: ${decisionType}`, reason);
    setShowDecisionModal(false);
    if (decisionType === 'approve') {
      setShowApprovalSuccessModal(true);
    } else {
      // Navigate back to queue
      navigate('/attorney/review');
    }
  };

  const getConfidenceColor = (confidence: string) => {
    switch (confidence) {
      case 'high':
        return 'bg-green-100 text-green-700 border-green-200';
      case 'medium':
        return 'bg-yellow-100 text-yellow-700 border-yellow-200';
      case 'low':
        return 'bg-red-100 text-red-700 border-red-200';
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200';
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return 'bg-red-100 text-red-700';
      case 'high':
        return 'bg-orange-100 text-orange-700';
      case 'medium':
        return 'bg-yellow-100 text-yellow-700';
      case 'low':
        return 'bg-blue-100 text-blue-700';
      default:
        return 'bg-slate-100 text-slate-700';
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <Button
          variant="ghost"
          leftIcon={<ChevronLeft className="w-4 h-4" />}
          onClick={() => navigate('/attorney/review')}
          className="mb-4"
        >
          Back to Queue
        </Button>
        
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 mb-2">
              {caseData.clientName}
            </h1>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="default">{caseData.caseNumber}</Badge>
              <Badge variant="default" className={getPriorityColor(caseData.priority)}>
                {caseData.priority.toUpperCase()} PRIORITY
              </Badge>
              <Badge variant="info">{caseData.caseType}</Badge>
            </div>
          </div>

          {/* Decision Buttons */}
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              leftIcon={<XCircle className="w-4 h-4" />}
              onClick={() => handleDecision('reject')}
              className="border-red-300 text-red-700 hover:bg-red-50"
            >
              Reject
            </Button>
            <Button
              variant="outline"
              leftIcon={<AlertTriangle className="w-4 h-4" />}
              onClick={() => handleDecision('escalate')}
              className="border-yellow-600 text-yellow-700 hover:bg-yellow-50"
            >
              Escalate
            </Button>
            <Button
              variant="primary"
              leftIcon={<CheckCircle2 className="w-4 h-4" />}
              onClick={() => handleDecision('approve')}
            >
              Approve for Submission
            </Button>
          </div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                <Calendar className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <p className="text-xs text-slate-600">VCF Deadline</p>
                <p className="font-semibold text-slate-900">
                  {new Date(caseData.vcfDeadline).toLocaleDateString()}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                <Activity className="w-5 h-5 text-green-600" />
              </div>
              <div>
                <p className="text-xs text-slate-600">Medical Score</p>
                <p className="font-semibold text-slate-900">{caseData.medicalScore}%</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                <DollarSign className="w-5 h-5 text-purple-600" />
              </div>
              <div>
                <p className="text-xs text-slate-600">Est. Value</p>
                <p className="font-semibold text-slate-900">
                  ${(caseData.estimatedValue / 1000).toFixed(0)}K
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-yellow-100 rounded-lg flex items-center justify-center">
                <Clock className="w-5 h-5 text-yellow-600" />
              </div>
              <div>
                <p className="text-xs text-slate-600">Submitted</p>
                <p className="font-semibold text-slate-900">
                  {Math.floor((new Date().getTime() - new Date(caseData.submittedDate).getTime()) / (1000 * 60 * 60 * 24))} days ago
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* AI Medical Summary */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-start gap-3 mb-4">
                <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-blue-500 rounded-lg flex items-center justify-center">
                  <Brain className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1">
                  <h2 className="text-xl font-bold text-slate-900">AI Medical Summary</h2>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-sm text-slate-600">Confidence:</span>
                    <Badge
                      variant="default"
                      className={`text-xs border ${getConfidenceColor(caseData.medicalConfidence)}`}
                    >
                      {caseData.medicalConfidence.toUpperCase()}
                    </Badge>
                    <span className="text-sm font-semibold text-slate-900">
                      {caseData.medicalScore}%
                    </span>
                  </div>
                </div>
              </div>
              <div className="bg-gradient-to-br from-blue-50 to-purple-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-line">
                  {caseData.aiSummary}
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Client Information */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-bold text-slate-900 mb-4">Client Information</h2>
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <dt className="text-sm text-slate-600">Full Name</dt>
                  <dd className="font-medium text-slate-900">{caseData.clientName}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Date of Birth</dt>
                  <dd className="font-medium text-slate-900">
                    {new Date(caseData.clientDOB).toLocaleDateString()}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Case Type</dt>
                  <dd className="font-medium text-slate-900 capitalize">{caseData.caseType}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Submitted By</dt>
                  <dd className="font-medium text-slate-900">{caseData.submittedBy}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          {/* WTC Exposure */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-bold text-slate-900 mb-4">WTC Exposure History</h2>
              <dl className="space-y-4">
                <div>
                  <dt className="text-sm text-slate-600">Exposure Type</dt>
                  <dd className="font-medium text-slate-900">{caseData.exposureType}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Location</dt>
                  <dd className="font-medium text-slate-900">{caseData.exposureLocation}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Exposure Period</dt>
                  <dd className="font-medium text-slate-900">{caseData.exposureDates}</dd>
                </div>
                <div>
                  <dt className="text-sm text-slate-600">Occupation</dt>
                  <dd className="font-medium text-slate-900">{caseData.occupation}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>

          {/* Medical Conditions */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-bold text-slate-900 mb-4">Medical Conditions</h2>
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {caseData.medicalConditions.map((condition, idx) => (
                    <Badge key={idx} variant="default" className="bg-blue-100 text-blue-700">
                      {condition}
                    </Badge>
                  ))}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-slate-200">
                  <div>
                    <dt className="text-sm text-slate-600">First Diagnosis</dt>
                    <dd className="font-medium text-slate-900">
                      {new Date(caseData.diagnosisDate).toLocaleDateString()}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-slate-600">Treating Physician</dt>
                    <dd className="font-medium text-slate-900">{caseData.treatingPhysician}</dd>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Documents */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-bold text-slate-900 mb-4">Documents</h2>
              <div className="space-y-6">
                {caseData.documents.map((category, idx) => (
                  <div key={idx}>
                    <h3 className="font-semibold text-slate-900 mb-3">{category.category}</h3>
                    <div className="space-y-2">
                      {category.files.map((file, fileIdx) => (
                        <div
                          key={fileIdx}
                          className="flex items-center justify-between p-3 bg-slate-50 border border-slate-200 rounded-lg"
                        >
                          <div className="flex items-center gap-3">
                            <FileText className="w-5 h-5 text-slate-600" />
                            <div>
                              <p className="text-sm font-medium text-slate-900">{file.name}</p>
                              <p className="text-xs text-slate-600">
                                Uploaded {new Date(file.uploadedDate).toLocaleDateString()}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <Badge variant="success" className="text-xs">
                              {file.status}
                            </Badge>
                            <Button variant="ghost" size="sm">
                              <Download className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Paralegal Notes */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-bold text-slate-900 mb-4">Paralegal Notes & Recommendation</h2>
              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
                <p className="text-sm text-slate-800 leading-relaxed whitespace-pre-line">
                  {caseData.paralegalNotes}
                </p>
              </div>
              <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
                <User className="w-4 h-4" />
                <span>Prepared by {caseData.submittedBy}</span>
                <span>•</span>
                <span>{new Date(caseData.submittedDate).toLocaleDateString()}</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Decision History */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-lg font-bold text-slate-900 mb-4">Decision History</h2>
              {caseData.decisionHistory.length === 0 ? (
                <div className="text-center py-8">
                  <Clock className="w-12 h-12 text-slate-300 mx-auto mb-3" />
                  <p className="text-sm text-slate-600">No decisions yet</p>
                  <p className="text-xs text-slate-500 mt-1">
                    This case is awaiting first review
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {caseData.decisionHistory.map((decision) => (
                    <div key={decision.id} className="border-l-2 border-slate-300 pl-4">
                      <div className="flex items-center gap-2 mb-1">
                        {decision.decision === 'approved' && (
                          <CheckCircle2 className="w-4 h-4 text-green-600" />
                        )}
                        {decision.decision === 'rejected' && (
                          <XCircle className="w-4 h-4 text-red-600" />
                        )}
                        {decision.decision === 'escalated' && (
                          <AlertTriangle className="w-4 h-4 text-yellow-600" />
                        )}
                        <span className="font-semibold text-sm text-slate-900 capitalize">
                          {decision.decision}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600">{decision.reviewer}</p>
                      <p className="text-xs text-slate-500">
                        {new Date(decision.date).toLocaleDateString()}
                      </p>
                      {decision.reason && (
                        <p className="text-xs text-slate-700 mt-2 italic">"{decision.reason}"</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quick Actions */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-lg font-bold text-slate-900 mb-4">Quick Actions</h2>
              <div className="space-y-2">
                <Button variant="outline" fullWidth className="justify-start">
                  <Download className="w-4 h-4 mr-2" />
                  Download All Documents
                </Button>
                <Button variant="outline" fullWidth className="justify-start">
                  <ExternalLink className="w-4 h-4 mr-2" />
                  View in Case Management
                </Button>
                <Button variant="outline" fullWidth className="justify-start">
                  <User className="w-4 h-4 mr-2" />
                  Contact Paralegal
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Review Checklist */}
          <Card>
            <CardContent className="p-6">
              <h2 className="text-lg font-bold text-slate-900 mb-4">Review Checklist</h2>
              <div className="space-y-3">
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1" defaultChecked />
                  <span className="text-sm text-slate-700">
                    Verified client identity and eligibility
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1" defaultChecked />
                  <span className="text-sm text-slate-700">
                    Reviewed all medical documentation
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1" defaultChecked />
                  <span className="text-sm text-slate-700">
                    Confirmed WTC exposure evidence
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1" />
                  <span className="text-sm text-slate-700">
                    Assessed medical causation strength
                  </span>
                </label>
                <label className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1" />
                  <span className="text-sm text-slate-700">
                    Reviewed paralegal notes and recommendation
                  </span>
                </label>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Decision Modal */}
      {showDecisionModal && (
        <DecisionModal
          isOpen={showDecisionModal}
          onClose={() => setShowDecisionModal(false)}
          onSubmit={handleDecisionSubmit}
          decisionType={decisionType}
          caseNumber={caseData.caseNumber}
          clientName={caseData.clientName}
        />
      )}

      {/* Approval Success Modal */}
      {showApprovalSuccessModal && (
        <ApprovalSuccessModal
          isOpen={showApprovalSuccessModal}
          onClose={() => setShowApprovalSuccessModal(false)}
          caseNumber={caseData.caseNumber}
          clientName={caseData.clientName}
          caseId={caseData.id}
        />
      )}
    </div>
  );
}