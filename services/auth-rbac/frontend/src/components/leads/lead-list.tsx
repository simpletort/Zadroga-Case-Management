import React, { useState, useMemo } from 'react';
import { Link } from 'react-router';
import { Input } from '../ui/input';
import { Select } from '../ui/select';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Card, CardContent } from '../ui/card';
import { Table, TableHead, TableBody, TableRow, TableHeader, TableCell } from '../ui/table';
import { Checkbox } from '../ui/checkbox';
import { Dropdown } from '../ui/dropdown';
import { Modal, ModalFooter } from '../ui/modal';
import { useToast } from '../ui/toast-provider';
import { Search, Filter, Download, UserPlus, MoreVertical, FileText, Calendar, Mail, Phone, CheckCircle2, XCircle, Clock, AlertCircle } from 'lucide-react';
import { Lead, LeadStatus, LeadSource } from '../../types';
import { mockLeads } from '../../mock-data';

/**
 * Lead List View - Main admin screen for managing leads
 * Features:
 * - Filterable by status, date range, source
 * - Sortable columns
 * - Batch operations
 * - Lead-to-case conversion
 */
export function LeadList() {
  const [leads] = useState<Lead[]>(mockLeads);
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [dateFilter, setDateFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('createdAt');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [convertModalOpen, setConvertModalOpen] = useState(false);
  const [batchActionModalOpen, setBatchActionModalOpen] = useState(false);
  const { addToast } = useToast();

  // Filter and sort leads
  const filteredLeads = useMemo(() => {
    let filtered = leads.filter(lead => {
      // Search filter
      const searchLower = searchQuery.toLowerCase();
      const matchesSearch = !searchQuery || 
        lead.firstName.toLowerCase().includes(searchLower) ||
        lead.lastName.toLowerCase().includes(searchLower) ||
        lead.email.toLowerCase().includes(searchLower) ||
        lead.phone.includes(searchQuery);

      // Status filter
      const matchesStatus = statusFilter === 'all' || lead.status === statusFilter;

      // Source filter
      const matchesSource = sourceFilter === 'all' || lead.source === sourceFilter;

      // Date filter
      const leadDate = new Date(lead.createdAt);
      const now = new Date();
      let matchesDate = true;
      
      if (dateFilter === 'today') {
        matchesDate = leadDate.toDateString() === now.toDateString();
      } else if (dateFilter === 'week') {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        matchesDate = leadDate >= weekAgo;
      } else if (dateFilter === 'month') {
        const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        matchesDate = leadDate >= monthAgo;
      }

      return matchesSearch && matchesStatus && matchesSource && matchesDate;
    });

    // Sort
    filtered.sort((a, b) => {
      let aVal: any = a[sortBy as keyof Lead];
      let bVal: any = b[sortBy as keyof Lead];

      if (sortBy === 'createdAt') {
        aVal = new Date(aVal).getTime();
        bVal = new Date(bVal).getTime();
      }

      if (sortOrder === 'asc') {
        return aVal > bVal ? 1 : -1;
      } else {
        return aVal < bVal ? 1 : -1;
      }
    });

    return filtered;
  }, [leads, searchQuery, statusFilter, sourceFilter, dateFilter, sortBy, sortOrder]);

  // Toggle lead selection
  const toggleLeadSelection = (leadId: string) => {
    const newSelected = new Set(selectedLeads);
    if (newSelected.has(leadId)) {
      newSelected.delete(leadId);
    } else {
      newSelected.add(leadId);
    }
    setSelectedLeads(newSelected);
  };

  // Select all filtered leads
  const toggleSelectAll = () => {
    if (selectedLeads.size === filteredLeads.length) {
      setSelectedLeads(new Set());
    } else {
      setSelectedLeads(new Set(filteredLeads.map(l => l.id)));
    }
  };

  // Get status badge variant
  const getStatusBadge = (status: LeadStatus) => {
    const statusConfig = {
      new: { variant: 'info' as const, icon: Clock, label: 'New' },
      contacted: { variant: 'warning' as const, icon: Mail, label: 'Contacted' },
      qualified: { variant: 'success' as const, icon: CheckCircle2, label: 'Qualified' },
      disqualified: { variant: 'error' as const, icon: XCircle, label: 'Disqualified' },
      converted: { variant: 'success' as const, icon: CheckCircle2, label: 'Converted' },
    };

    const config = statusConfig[status];
    const Icon = config.icon;

    return (
      <Badge variant={config.variant} className="flex items-center gap-1">
        <Icon className="w-3 h-3" />
        {config.label}
      </Badge>
    );
  };

  // Convert leads to cases
  const handleConvertToCases = () => {
    const selectedCount = selectedLeads.size;
    // In real app, this would make API calls
    addToast({
      variant: 'success',
      title: 'Success',
      message: `${selectedCount} lead(s) converted to cases successfully!`
    });
    setSelectedLeads(new Set());
    setConvertModalOpen(false);
  };

  // Batch update status
  const handleBatchStatusUpdate = (newStatus: LeadStatus) => {
    const selectedCount = selectedLeads.size;
    // In real app, this would make API calls
    addToast({
      variant: 'success',
      title: 'Success',
      message: `${selectedCount} lead(s) updated to ${newStatus}`
    });
    setSelectedLeads(new Set());
    setBatchActionModalOpen(false);
  };

  // Export leads
  const handleExport = () => {
    addToast({
      variant: 'info',
      message: 'Exporting leads to CSV...'
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Lead Intake</h1>
          <p className="text-slate-600 mt-1">
            Manage and convert leads into cases
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" leftIcon={<Download className="w-4 h-4" />} onClick={handleExport}>
            Export
          </Button>
          <Button variant="primary" leftIcon={<UserPlus className="w-4 h-4" />}>
            Add Lead
          </Button>
        </div>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Total Leads</p>
                <p className="text-2xl font-bold text-slate-900 mt-1">{leads.length}</p>
              </div>
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <UserPlus className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">New Leads</p>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {leads.filter(l => l.status === 'new').length}
                </p>
              </div>
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                <Clock className="w-6 h-6 text-purple-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Qualified</p>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {leads.filter(l => l.status === 'qualified').length}
                </p>
              </div>
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <CheckCircle2 className="w-6 h-6 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-600">Conversion Rate</p>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {Math.round((leads.filter(l => l.status === 'converted').length / leads.length) * 100)}%
                </p>
              </div>
              <div className="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-yellow-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters & Search */}
      <Card>
        <CardContent className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="lg:col-span-2">
              <Input
                placeholder="Search by name, email, or phone..."
                leftIcon={<Search className="w-5 h-5" />}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                fullWidth
              />
            </div>

            <Select
              placeholder="All Statuses"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              options={[
                { value: 'all', label: 'All Statuses' },
                { value: 'new', label: 'New' },
                { value: 'contacted', label: 'Contacted' },
                { value: 'qualified', label: 'Qualified' },
                { value: 'disqualified', label: 'Disqualified' },
                { value: 'converted', label: 'Converted' },
              ]}
              fullWidth
            />

            <Select
              placeholder="All Sources"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              options={[
                { value: 'all', label: 'All Sources' },
                { value: 'SLG', label: 'SLG' },
                { value: 'Shapiro Law Group', label: 'Shapiro Law Group' },
                { value: 'Direct', label: 'Direct' },
              ]}
              fullWidth
            />

            <Select
              placeholder="All Time"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              options={[
                { value: 'all', label: 'All Time' },
                { value: 'today', label: 'Today' },
                { value: 'week', label: 'Last 7 Days' },
                { value: 'month', label: 'Last 30 Days' },
              ]}
              fullWidth
            />
          </div>

          {/* Batch Actions */}
          {selectedLeads.size > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-200">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <p className="text-sm text-slate-700">
                  <span className="font-semibold">{selectedLeads.size}</span> lead(s) selected
                </p>
                <div className="flex gap-2">
                  <Button 
                    size="sm" 
                    variant="outline"
                    onClick={() => setBatchActionModalOpen(true)}
                  >
                    Update Status
                  </Button>
                  <Button 
                    size="sm" 
                    variant="primary"
                    onClick={() => setConvertModalOpen(true)}
                  >
                    Convert to Cases
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Leads Table - Desktop */}
      <div className="hidden md:block">
        <Card padding="none">
          <Table striped hoverable>
            <TableHead>
              <TableRow>
                <TableHeader className="w-12">
                  <Checkbox
                    checked={selectedLeads.size === filteredLeads.length && filteredLeads.length > 0}
                    onChange={toggleSelectAll}
                  />
                </TableHeader>
                <TableHeader>Name</TableHeader>
                <TableHeader>Contact</TableHeader>
                <TableHeader>Source</TableHeader>
                <TableHeader>Status</TableHeader>
                <TableHeader>VCF Score</TableHeader>
                <TableHeader>Created</TableHeader>
                <TableHeader className="w-12"></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredLeads.map((lead) => (
                <TableRow key={lead.id}>
                  <TableCell>
                    <Checkbox
                      checked={selectedLeads.has(lead.id)}
                      onChange={() => toggleLeadSelection(lead.id)}
                    />
                  </TableCell>
                  <TableCell>
                    <Link 
                      to={`/leads/${lead.id}`}
                      className="font-medium text-blue-600 hover:text-blue-700 hover:underline"
                    >
                      {lead.firstName} {lead.lastName}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <Mail className="w-3.5 h-3.5 text-slate-400" />
                        {lead.email}
                      </div>
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <Phone className="w-3.5 h-3.5 text-slate-400" />
                        {lead.phone}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="default">
                      {lead.source.charAt(0).toUpperCase() + lead.source.slice(1)}
                    </Badge>
                  </TableCell>
                  <TableCell>{getStatusBadge(lead.status)}</TableCell>
                  <TableCell>
                    {lead.vcfScreening ? (
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-semibold text-slate-900">
                          {lead.vcfScreening.score}/100
                        </div>
                        {lead.vcfScreening.qualified ? (
                          <CheckCircle2 className="w-4 h-4 text-green-600" />
                        ) : (
                          <XCircle className="w-4 h-4 text-red-600" />
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-slate-400">Not screened</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="text-sm text-slate-700">
                      {new Date(lead.createdAt).toLocaleDateString()}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Dropdown
                      trigger={
                        <Button variant="ghost" size="sm">
                          <MoreVertical className="w-4 h-4" />
                        </Button>
                      }
                      items={[
                        { 
                          id: 'view', 
                          label: 'View Details',
                          onClick: () => {} 
                        },
                        { 
                          id: 'convert', 
                          label: 'Convert to Case',
                          onClick: () => {
                            setSelectedLeads(new Set([lead.id]));
                            setConvertModalOpen(true);
                          }
                        },
                      ]}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {filteredLeads.length === 0 && (
            <div className="text-center py-12">
              <AlertCircle className="w-12 h-12 text-slate-400 mx-auto mb-4" />
              <p className="text-slate-600">No leads found matching your filters</p>
            </div>
          )}
        </Card>
      </div>

      {/* Leads Cards - Mobile */}
      <div className="md:hidden space-y-4">
        {filteredLeads.map((lead) => (
          <Card key={lead.id} hoverable>
            <CardContent className="p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={selectedLeads.has(lead.id)}
                    onChange={() => toggleLeadSelection(lead.id)}
                  />
                  <div>
                    <Link 
                      to={`/leads/${lead.id}`}
                      className="font-semibold text-slate-900 hover:text-blue-600"
                    >
                      {lead.firstName} {lead.lastName}
                    </Link>
                    <div className="flex items-center gap-2 mt-1">
                      {getStatusBadge(lead.status)}
                      <Badge variant="default" className="text-xs">
                        {lead.source}
                      </Badge>
                    </div>
                  </div>
                </div>
                <Dropdown
                  trigger={
                    <Button variant="ghost" size="sm">
                      <MoreVertical className="w-4 h-4" />
                    </Button>
                  }
                  items={[
                    { id: 'view', label: 'View Details', onClick: () => {} },
                    { id: 'convert', label: 'Convert to Case', onClick: () => {} },
                  ]}
                />
              </div>

              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2 text-slate-600">
                  <Mail className="w-4 h-4" />
                  {lead.email}
                </div>
                <div className="flex items-center gap-2 text-slate-600">
                  <Phone className="w-4 h-4" />
                  {lead.phone}
                </div>
                <div className="flex items-center gap-2 text-slate-600">
                  <Calendar className="w-4 h-4" />
                  {new Date(lead.createdAt).toLocaleDateString()}
                </div>
              </div>

              {lead.vcfScreening && (
                <div className="mt-3 pt-3 border-t border-slate-200">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-600">VCF Score</span>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-900">
                        {lead.vcfScreening.score}/100
                      </span>
                      {lead.vcfScreening.qualified ? (
                        <CheckCircle2 className="w-4 h-4 text-green-600" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-600" />
                      )}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Convert to Cases Modal */}
      <Modal
        open={convertModalOpen}
        onClose={() => setConvertModalOpen(false)}
        title="Convert Leads to Cases"
        size="md"
      >
        <div className="space-y-4">
          <p className="text-slate-700">
            You are about to convert <strong>{selectedLeads.size}</strong> lead(s) into case(s).
            This action will:
          </p>
          <ul className="list-disc list-inside space-y-2 text-sm text-slate-600">
            <li>Create new case records with all lead data</li>
            <li>Assign cases to available paralegals</li>
            <li>Mark leads as "Converted"</li>
            <li>Generate initial document checklists</li>
          </ul>
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex gap-3">
              <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-yellow-900">Important</p>
                <p className="text-sm text-yellow-700 mt-1">
                  This action cannot be undone. Make sure all lead information is accurate.
                </p>
              </div>
            </div>
          </div>
        </div>

        <ModalFooter>
          <Button variant="outline" onClick={() => setConvertModalOpen(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleConvertToCases}>
            Convert to Cases
          </Button>
        </ModalFooter>
      </Modal>

      {/* Batch Status Update Modal */}
      <Modal
        open={batchActionModalOpen}
        onClose={() => setBatchActionModalOpen(false)}
        title="Update Lead Status"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-slate-700">
            Update status for <strong>{selectedLeads.size}</strong> selected lead(s):
          </p>
          <div className="space-y-2">
            <Button 
              variant="outline" 
              fullWidth 
              onClick={() => handleBatchStatusUpdate('contacted')}
            >
              Mark as Contacted
            </Button>
            <Button 
              variant="outline" 
              fullWidth 
              onClick={() => handleBatchStatusUpdate('qualified')}
            >
              Mark as Qualified
            </Button>
            <Button 
              variant="outline" 
              fullWidth 
              onClick={() => handleBatchStatusUpdate('disqualified')}
            >
              Mark as Disqualified
            </Button>
          </div>
        </div>

        <ModalFooter>
          <Button variant="outline" onClick={() => setBatchActionModalOpen(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}