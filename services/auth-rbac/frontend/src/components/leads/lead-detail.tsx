import React, { useState } from 'react';
import { useParams, Link } from 'react-router';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Card, CardHeader, CardContent } from '../ui/card';
import { Tabs } from '../ui/tabs';
import { Progress } from '../ui/progress';
import { Modal, ModalFooter } from '../ui/modal';
import { Alert } from '../ui/alert';
import { useToast } from '../ui/toast-provider';
import { 
  ArrowLeft, 
  Mail, 
  Phone, 
  MapPin, 
  Calendar, 
  FileText, 
  CheckCircle2, 
  XCircle,
  AlertCircle,
  User,
  Activity,
  MessageSquare,
  Edit,
  Trash2
} from 'lucide-react';
import { Lead } from '../../types';
import { mockLeads } from '../../mock-data';

/**
 * Lead Detail View - Comprehensive view of individual lead
 * Features:
 * - All captured lead data
 * - VCF screening results with visualization
 * - Lead-to-case conversion action
 * - Activity timeline
 * - Notes/communications
 */
export function LeadDetail() {
  const { leadId } = useParams();
  const [convertModalOpen, setConvertModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const { addToast } = useToast();

  // Get lead data (in real app, fetch from API)
  const lead = mockLeads.find(l => l.id === leadId);

  if (!lead) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="w-16 h-16 text-slate-400 mx-auto mb-4" />
        <h2 className="text-2xl font-bold text-slate-900 mb-2">Lead Not Found</h2>
        <p className="text-slate-600 mb-6">The lead you're looking for doesn't exist.</p>
        <Link to="/leads">
          <Button variant="primary">Back to Leads</Button>
        </Link>
      </div>
    );
  }

  const handleConvertToCase = () => {
    addToast({
      variant: 'success',
      title: 'Success',
      message: 'Lead converted to case successfully!'
    });
    setConvertModalOpen(false);
    // In real app, navigate to new case
  };

  const handleDeleteLead = () => {
    addToast({
      variant: 'success',
      message: 'Lead deleted successfully'
    });
    setDeleteModalOpen(false);
    // In real app, navigate back to list
  };

  const getStatusBadge = (status: string) => {
    const statusConfig: Record<string, { variant: any; label: string }> = {
      new: { variant: 'info', label: 'New' },
      contacted: { variant: 'warning', label: 'Contacted' },
      qualified: { variant: 'success', label: 'Qualified' },
      disqualified: { variant: 'error', label: 'Disqualified' },
      converted: { variant: 'success', label: 'Converted' },
    };

    const config = statusConfig[status] || { variant: 'default', label: status };
    return <Badge variant={config.variant}>{config.label}</Badge>;
  };

  const getConfidenceColor = (confidence: string) => {
    if (confidence === 'high') return 'text-green-600';
    if (confidence === 'medium') return 'text-yellow-600';
    return 'text-red-600';
  };

  const getConfidenceBg = (confidence: string) => {
    if (confidence === 'high') return 'bg-green-100';
    if (confidence === 'medium') return 'bg-yellow-100';
    return 'bg-red-100';
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link to="/leads" className="inline-flex items-center gap-2 text-slate-600 hover:text-slate-900 mb-4">
          <ArrowLeft className="w-4 h-4" />
          Back to Leads
        </Link>

        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-3xl font-bold text-slate-900">
                {lead.firstName} {lead.lastName}
              </h1>
              {getStatusBadge(lead.status)}
            </div>
            <p className="text-slate-600">
              Lead ID: #{lead.id} • Created {new Date(lead.createdAt).toLocaleDateString()}
            </p>
          </div>

          <div className="flex gap-3">
            <Button 
              variant="outline" 
              leftIcon={<Edit className="w-4 h-4" />}
            >
              Edit Lead
            </Button>
            {lead.status !== 'converted' && (
              <Button 
                variant="primary"
                onClick={() => setConvertModalOpen(true)}
              >
                Convert to Case
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* VCF Qualification Alert */}
      {lead.vcfScreening && (
        <Alert 
          variant={lead.vcfScreening.qualified ? 'success' : 'warning'}
          title={lead.vcfScreening.qualified ? 'VCF Qualified' : 'Review Required'}
        >
          {lead.vcfScreening.qualified 
            ? 'This lead meets VCF qualification criteria and is ready for case conversion.'
            : 'This lead may not meet all VCF qualification requirements. Review screening results below.'}
        </Alert>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          <Tabs
            tabs={[
              {
                id: 'overview',
                label: 'Overview',
                content: (
                  <div className="space-y-6">
                    {/* Contact Information */}
                    <Card>
                      <CardHeader title="Contact Information" />
                      <CardContent>
                        <div className="grid sm:grid-cols-2 gap-4">
                          <div className="flex items-start gap-3">
                            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                              <Mail className="w-5 h-5 text-blue-600" />
                            </div>
                            <div>
                              <p className="text-sm text-slate-600">Email</p>
                              <p className="font-medium text-slate-900">{lead.email}</p>
                            </div>
                          </div>

                          <div className="flex items-start gap-3">
                            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                              <Phone className="w-5 h-5 text-blue-600" />
                            </div>
                            <div>
                              <p className="text-sm text-slate-600">Phone</p>
                              <p className="font-medium text-slate-900">{lead.phone}</p>
                            </div>
                          </div>

                          <div className="flex items-start gap-3">
                            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                              <MapPin className="w-5 h-5 text-blue-600" />
                            </div>
                            <div>
                              <p className="text-sm text-slate-600">Address</p>
                              <p className="font-medium text-slate-900">{lead.address}</p>
                              <p className="text-sm text-slate-600">
                                {lead.city}, {lead.state} {lead.zipCode}
                              </p>
                            </div>
                          </div>

                          <div className="flex items-start gap-3">
                            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                              <Calendar className="w-5 h-5 text-blue-600" />
                            </div>
                            <div>
                              <p className="text-sm text-slate-600">Date of Birth</p>
                              <p className="font-medium text-slate-900">
                                {lead.dateOfBirth ? new Date(lead.dateOfBirth).toLocaleDateString() : 'Not provided'}
                              </p>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>

                    {/* Case Information */}
                    <Card>
                      <CardHeader title="Case Information" />
                      <CardContent>
                        <div className="space-y-4">
                          <div>
                            <p className="text-sm text-slate-600 mb-1">Injury Description</p>
                            <p className="text-slate-900">{lead.injuryDescription}</p>
                          </div>

                          <div className="grid sm:grid-cols-2 gap-4">
                            <div>
                              <p className="text-sm text-slate-600 mb-1">Exposure Location</p>
                              <p className="font-medium text-slate-900">{lead.exposureLocation}</p>
                            </div>

                            <div>
                              <p className="text-sm text-slate-600 mb-1">Exposure Dates</p>
                              <p className="font-medium text-slate-900">
                                {new Date(lead.exposureStartDate).toLocaleDateString()} - 
                                {new Date(lead.exposureEndDate).toLocaleDateString()}
                              </p>
                            </div>
                          </div>

                          {lead.medicalDocuments && lead.medicalDocuments.length > 0 && (
                            <div>
                              <p className="text-sm text-slate-600 mb-2">Medical Documents</p>
                              <div className="space-y-2">
                                {lead.medicalDocuments.map((doc, idx) => (
                                  <div key={idx} className="flex items-center gap-2 p-2 bg-slate-50 rounded">
                                    <FileText className="w-4 h-4 text-slate-400" />
                                    <span className="text-sm text-slate-700">{doc}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                ),
              },
              {
                id: 'screening',
                label: 'VCF Screening',
                content: lead.vcfScreening ? (
                  <div className="space-y-6">
                    {/* Screening Score */}
                    <Card>
                      <CardHeader title="Screening Results" />
                      <CardContent>
                        <div className="flex items-center justify-between mb-6">
                          <div>
                            <p className="text-sm text-slate-600">Overall Score</p>
                            <p className="text-4xl font-bold text-slate-900 mt-1">
                              {lead.vcfScreening.score}
                              <span className="text-lg text-slate-600">/100</span>
                            </p>
                          </div>
                          <div className={`w-20 h-20 rounded-full flex items-center justify-center ${
                            lead.vcfScreening.qualified ? 'bg-green-100' : 'bg-red-100'
                          }`}>
                            {lead.vcfScreening.qualified ? (
                              <CheckCircle2 className="w-10 h-10 text-green-600" />
                            ) : (
                              <XCircle className="w-10 h-10 text-red-600" />
                            )}
                          </div>
                        </div>

                        <Progress 
                          value={lead.vcfScreening.score} 
                          variant={lead.vcfScreening.qualified ? 'success' : 'warning'}
                          showLabel
                        />

                        <div className="mt-6 p-4 bg-slate-50 rounded-lg">
                          <div className="flex items-start gap-3">
                            <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                              getConfidenceBg(lead.vcfScreening.confidence)
                            } ${getConfidenceColor(lead.vcfScreening.confidence)}`}>
                              {lead.vcfScreening.confidence.toUpperCase()} CONFIDENCE
                            </div>
                          </div>
                          <p className="text-sm text-slate-600 mt-3">
                            AI confidence level based on provided information and historical data patterns.
                          </p>
                        </div>
                      </CardContent>
                    </Card>

                    {/* Qualification Criteria */}
                    <Card>
                      <CardHeader title="Qualification Criteria" subtitle="VCF eligibility requirements" />
                      <CardContent>
                        <div className="space-y-4">
                          {lead.vcfScreening.criteria.map((criterion, idx) => (
                            <div 
                              key={idx}
                              className="flex items-start gap-3 p-4 bg-slate-50 rounded-lg"
                            >
                              {criterion.met ? (
                                <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                              ) : (
                                <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                              )}
                              <div className="flex-1">
                                <p className="font-medium text-slate-900">{criterion.name}</p>
                                <p className="text-sm text-slate-600 mt-1">{criterion.description}</p>
                                {criterion.notes && (
                                  <div className="mt-2 p-2 bg-white rounded border border-slate-200">
                                    <p className="text-sm text-slate-700">{criterion.notes}</p>
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </CardContent>
                    </Card>

                    {/* Red Flags */}
                    {lead.vcfScreening.redFlags && lead.vcfScreening.redFlags.length > 0 && (
                      <Card>
                        <CardHeader 
                          title="Red Flags" 
                          subtitle="Potential issues requiring review"
                        />
                        <CardContent>
                          <div className="space-y-3">
                            {lead.vcfScreening.redFlags.map((flag, idx) => (
                              <Alert key={idx} variant="warning">
                                {flag}
                              </Alert>
                            ))}
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-12">
                    <AlertCircle className="w-12 h-12 text-slate-400 mx-auto mb-4" />
                    <p className="text-slate-600">No VCF screening data available</p>
                    <Button variant="primary" className="mt-4">
                      Run VCF Screening
                    </Button>
                  </div>
                ),
              },
              {
                id: 'activity',
                label: 'Activity',
                content: (
                  <Card>
                    <CardContent>
                      <div className="space-y-6">
                        {/* Activity Timeline */}
                        <div className="space-y-4">
                          <div className="flex gap-4">
                            <div className="flex flex-col items-center">
                              <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">
                                <User className="w-5 h-5 text-blue-600" />
                              </div>
                              <div className="w-0.5 h-full bg-slate-200 mt-2"></div>
                            </div>
                            <div className="flex-1 pb-6">
                              <p className="font-medium text-slate-900">Lead Created</p>
                              <p className="text-sm text-slate-600 mt-1">
                                Lead submitted via {lead.source}
                              </p>
                              <p className="text-xs text-slate-500 mt-2">
                                {new Date(lead.createdAt).toLocaleString()}
                              </p>
                            </div>
                          </div>

                          {lead.vcfScreening && (
                            <div className="flex gap-4">
                              <div className="flex flex-col items-center">
                                <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center">
                                  <Activity className="w-5 h-5 text-green-600" />
                                </div>
                                <div className="w-0.5 h-full bg-slate-200 mt-2"></div>
                              </div>
                              <div className="flex-1 pb-6">
                                <p className="font-medium text-slate-900">VCF Screening Completed</p>
                                <p className="text-sm text-slate-600 mt-1">
                                  Score: {lead.vcfScreening.score}/100 - 
                                  {lead.vcfScreening.qualified ? ' Qualified' : ' Needs Review'}
                                </p>
                                <p className="text-xs text-slate-500 mt-2">
                                  {new Date(lead.createdAt).toLocaleString()}
                                </p>
                              </div>
                            </div>
                          )}

                          <div className="flex gap-4">
                            <div className="flex flex-col items-center">
                              <div className="w-10 h-10 bg-purple-100 rounded-full flex items-center justify-center">
                                <MessageSquare className="w-5 h-5 text-purple-600" />
                              </div>
                            </div>
                            <div className="flex-1">
                              <p className="font-medium text-slate-900">Status Updated</p>
                              <p className="text-sm text-slate-600 mt-1">
                                Changed to {lead.status}
                              </p>
                              <p className="text-xs text-slate-500 mt-2">
                                {new Date(lead.createdAt).toLocaleString()}
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ),
              },
            ]}
          />
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Quick Actions */}
          <Card>
            <CardHeader title="Quick Actions" />
            <CardContent>
              <div className="space-y-2">
                <Button variant="outline" fullWidth leftIcon={<Mail className="w-4 h-4" />}>
                  Send Email
                </Button>
                <Button variant="outline" fullWidth leftIcon={<Phone className="w-4 h-4" />}>
                  Call Lead
                </Button>
                <Button variant="outline" fullWidth leftIcon={<MessageSquare className="w-4 h-4" />}>
                  Add Note
                </Button>
                <Button variant="outline" fullWidth leftIcon={<FileText className="w-4 h-4" />}>
                  Upload Document
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Lead Source */}
          <Card>
            <CardHeader title="Lead Source" />
            <CardContent>
              <Badge variant="default" className="mb-3">
                {lead.source.charAt(0).toUpperCase() + lead.source.slice(1)}
              </Badge>
              <p className="text-sm text-slate-600">
                Submitted on {new Date(lead.createdAt).toLocaleDateString()}
              </p>
            </CardContent>
          </Card>

          {/* Danger Zone */}
          <Card>
            <CardHeader title="Danger Zone" />
            <CardContent>
              <Button 
                variant="danger" 
                fullWidth 
                leftIcon={<Trash2 className="w-4 h-4" />}
                onClick={() => setDeleteModalOpen(true)}
              >
                Delete Lead
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Convert Modal */}
      <Modal
        open={convertModalOpen}
        onClose={() => setConvertModalOpen(false)}
        title="Convert Lead to Case"
        size="md"
      >
        <div className="space-y-4">
          <p className="text-slate-700">
            Convert <strong>{lead.firstName} {lead.lastName}</strong> into a case?
          </p>

          {lead.vcfScreening && (
            <div className={`p-4 rounded-lg ${
              lead.vcfScreening.qualified ? 'bg-green-50 border border-green-200' : 'bg-yellow-50 border border-yellow-200'
            }`}>
              <div className="flex items-start gap-3">
                {lead.vcfScreening.qualified ? (
                  <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                )}
                <div>
                  <p className="text-sm font-medium text-slate-900">
                    VCF Score: {lead.vcfScreening.score}/100
                  </p>
                  <p className="text-sm text-slate-600 mt-1">
                    {lead.vcfScreening.qualified 
                      ? 'Lead meets VCF qualification criteria'
                      : 'Review may be required before case creation'}
                  </p>
                </div>
              </div>
            </div>
          )}

          <ul className="list-disc list-inside space-y-2 text-sm text-slate-600">
            <li>Create new case record</li>
            <li>Assign to paralegal</li>
            <li>Generate document checklist</li>
            <li>Mark lead as converted</li>
          </ul>
        </div>

        <ModalFooter>
          <Button variant="outline" onClick={() => setConvertModalOpen(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleConvertToCase}>
            Convert to Case
          </Button>
        </ModalFooter>
      </Modal>

      {/* Delete Modal */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="Delete Lead"
        size="sm"
      >
        <div className="space-y-4">
          <Alert variant="error" title="Warning">
            This action cannot be undone. All lead data will be permanently deleted.
          </Alert>
          <p className="text-slate-700">
            Are you sure you want to delete this lead?
          </p>
        </div>

        <ModalFooter>
          <Button variant="outline" onClick={() => setDeleteModalOpen(false)}>
            Cancel
          </Button>
          <Button variant="danger" onClick={handleDeleteLead}>
            Delete Lead
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}