import React, { useState } from 'react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Textarea } from './ui/textarea';
import { Select } from './ui/select';
import { Checkbox } from './ui/checkbox';
import { Radio, RadioGroup } from './ui/radio';
import { Switch } from './ui/switch';
import { Badge } from './ui/badge';
import { Alert } from './ui/alert';
import { Card, CardHeader, CardContent, CardFooter } from './ui/card';
import { Modal, ModalFooter } from './ui/modal';
import { Tooltip } from './ui/tooltip';
import { Table, TableHead, TableBody, TableRow, TableHeader, TableCell } from './ui/table';
import { Tabs } from './ui/tabs';
import { Accordion } from './ui/accordion';
import { Progress } from './ui/progress';
import { Spinner } from './ui/spinner';
import { Avatar } from './ui/avatar';
import { Breadcrumb } from './ui/breadcrumb';
import { Pagination } from './ui/pagination';
import { ToastContainer, useToast } from './ui/toast';
import { Divider } from './ui/divider';
import { Dropdown } from './ui/dropdown';
import { Label } from './ui/label';
import { Plus, Trash2, Edit, Download, Settings, User, Mail, Phone, Search } from 'lucide-react';

/**
 * Design System Showcase
 * 
 * Comprehensive component library demonstration for the SimpleTort platform.
 * This page showcases all available UI components with examples and usage patterns.
 */
export function DesignSystemShowcase() {
  const [modalOpen, setModalOpen] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [switchChecked, setSwitchChecked] = useState(false);
  const [radioValue, setRadioValue] = useState('option1');
  const { toasts, addToast, dismissToast } = useToast();
  
  return (
    <div className="min-h-screen bg-slate-50 p-8">
      <div className="max-w-7xl mx-auto space-y-12">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-4xl font-bold text-slate-900 mb-4">
            SimpleTort Design System
          </h1>
          <p className="text-lg text-slate-600 max-w-3xl mx-auto">
            A comprehensive, accessible component library following WCAG 2.1 AA standards.
            Built with React, TypeScript, and Tailwind CSS.
          </p>
        </div>
        
        {/* Design Tokens */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Design Tokens</h2>
          
          <div className="grid gap-6">
            {/* Colors */}
            <Card>
              <CardHeader title="Color Palette" subtitle="Semantic color system with WCAG AA contrast ratios" />
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">Primary</p>
                    <div className="space-y-1">
                      <div className="h-12 bg-blue-300 rounded flex items-center justify-center text-blue-900 text-xs">300</div>
                      <div className="h-8 bg-blue-500 rounded flex items-center justify-center text-white text-xs">500</div>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">Success</p>
                    <div className="space-y-1">
                      <div className="h-12 bg-green-600 rounded flex items-center justify-center text-white text-xs">600</div>
                      <div className="h-8 bg-green-500 rounded flex items-center justify-center text-white text-xs">500</div>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">Warning</p>
                    <div className="space-y-1">
                      <div className="h-12 bg-yellow-600 rounded flex items-center justify-center text-white text-xs">600</div>
                      <div className="h-8 bg-yellow-500 rounded flex items-center justify-center text-white text-xs">500</div>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">Error</p>
                    <div className="space-y-1">
                      <div className="h-12 bg-red-600 rounded flex items-center justify-center text-white text-xs">600</div>
                      <div className="h-8 bg-red-500 rounded flex items-center justify-center text-white text-xs">500</div>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">Neutral</p>
                    <div className="space-y-1">
                      <div className="h-12 bg-slate-600 rounded flex items-center justify-center text-white text-xs">600</div>
                      <div className="h-8 bg-slate-500 rounded flex items-center justify-center text-white text-xs">500</div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
            
            {/* Typography */}
            <Card>
              <CardHeader title="Typography" subtitle="Font sizes and weights" />
              <CardContent>
                <div className="space-y-2">
                  <p className="text-xs text-slate-700">Extra Small (12px)</p>
                  <p className="text-sm text-slate-700">Small (14px)</p>
                  <p className="text-base text-slate-700">Base (16px)</p>
                  <p className="text-lg text-slate-700">Large (18px)</p>
                  <p className="text-xl text-slate-700">Extra Large (20px)</p>
                  <p className="text-2xl text-slate-700">2X Large (24px)</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
        
        {/* Buttons */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Buttons</h2>
          <Card>
            <CardContent>
              <div className="space-y-6">
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">Variants</h3>
                  <div className="flex flex-wrap gap-3">
                    <Button variant="primary" className="bg-blue-300 hover:bg-blue-400 text-blue-900">Primary</Button>
                    <Button variant="secondary" className="bg-teal-500 hover:bg-teal-600 text-white border-teal-500">Secondary</Button>
                    <Button variant="outline">Outline</Button>
                    <Button variant="ghost">Ghost</Button>
                    <Button variant="danger">Danger</Button>
                    <Button variant="success">Success</Button>
                  </div>
                </div>
                
                <Divider />
                
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">Sizes</h3>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button size="sm">Small</Button>
                    <Button size="md">Medium</Button>
                    <Button size="lg">Large</Button>
                  </div>
                </div>
                
                <Divider />
                
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">With Icons</h3>
                  <div className="flex flex-wrap gap-3">
                    <Button leftIcon={<Plus className="w-4 h-4" />}>Add New</Button>
                    <Button variant="outline" leftIcon={<Download className="w-4 h-4" />}>Download</Button>
                    <Button variant="danger" leftIcon={<Trash2 className="w-4 h-4" />}>Delete</Button>
                  </div>
                </div>
                
                <Divider />
                
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">States</h3>
                  <div className="flex flex-wrap gap-3">
                    <Button loading>Loading</Button>
                    <Button disabled>Disabled</Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
        
        {/* Form Controls */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Form Controls</h2>
          <Card>
            <CardContent>
              <div className="grid gap-6 max-w-2xl">
                <Input
                  label="Email Address"
                  type="email"
                  placeholder="you@example.com"
                  leftIcon={<Mail className="w-5 h-5" />}
                  required
                  fullWidth
                />
                
                <Input
                  label="Phone Number"
                  type="tel"
                  placeholder="(555) 123-4567"
                  leftIcon={<Phone className="w-5 h-5" />}
                  helperText="Include area code"
                  fullWidth
                />
                
                <Input
                  label="Search"
                  type="text"
                  placeholder="Search cases..."
                  leftIcon={<Search className="w-5 h-5" />}
                  fullWidth
                />
                
                <Textarea
                  label="Description"
                  rows={4}
                  placeholder="Enter description..."
                  maxLength={500}
                  showCount
                  fullWidth
                />
                
                <Select
                  label="Status"
                  placeholder="Select status"
                  options={[
                    { value: 'active', label: 'Active' },
                    { value: 'pending', label: 'Pending' },
                    { value: 'closed', label: 'Closed' },
                  ]}
                  fullWidth
                />
                
                <div className="space-y-3">
                  <Checkbox label="I agree to the terms and conditions" />
                  <Checkbox label="Subscribe to newsletter" />
                  <Checkbox label="Disabled option" disabled />
                </div>
                
                <RadioGroup
                  label="Select priority"
                  name="priority"
                  value={radioValue}
                  onChange={setRadioValue}
                  options={[
                    { value: 'option1', label: 'High Priority', description: 'Urgent cases' },
                    { value: 'option2', label: 'Normal Priority', description: 'Standard processing' },
                    { value: 'option3', label: 'Low Priority', description: 'Non-urgent' },
                  ]}
                />
                
                <Switch
                  label="Enable notifications"
                  description="Receive email updates"
                  checked={switchChecked}
                  onChange={(e) => setSwitchChecked(e.target.checked)}
                />
              </div>
            </CardContent>
          </Card>
        </section>
        
        {/* Badges & Alerts */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Badges & Alerts</h2>
          <div className="grid gap-6">
            <Card>
              <CardHeader title="Badges" />
              <CardContent>
                <div className="flex flex-wrap gap-3">
                  <Badge variant="default">Default</Badge>
                  <Badge variant="primary">Primary</Badge>
                  <Badge variant="success">Success</Badge>
                  <Badge variant="warning">Warning</Badge>
                  <Badge variant="error">Error</Badge>
                  <Badge variant="info">Info</Badge>
                  <Badge variant="success" dot>Active</Badge>
                  <Badge variant="error" dot>Critical</Badge>
                </div>
              </CardContent>
            </Card>
            
            <div className="space-y-4">
              <Alert variant="success" title="Success!" dismissible>
                Your changes have been saved successfully.
              </Alert>
              <Alert variant="info" title="Information">
                New updates are available. Please review the changes.
              </Alert>
              <Alert variant="warning" title="Warning">
                This action cannot be undone. Please proceed with caution.
              </Alert>
              <Alert variant="error" title="Error" dismissible>
                An error occurred while processing your request.
              </Alert>
            </div>
          </div>
        </section>
        
        {/* Cards */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Cards</h2>
          <div className="grid md:grid-cols-3 gap-6">
            <Card variant="default">
              <CardHeader title="Default Card" subtitle="Standard styling" />
              <CardContent>
                <p className="text-sm text-slate-600">
                  Card content goes here with default styling and padding.
                </p>
              </CardContent>
            </Card>
            
            <Card variant="bordered">
              <CardHeader title="Bordered Card" subtitle="With border emphasis" />
              <CardContent>
                <p className="text-sm text-slate-600">
                  Card with thicker border for visual emphasis.
                </p>
              </CardContent>
            </Card>
            
            <Card variant="elevated" hoverable>
              <CardHeader title="Elevated Card" subtitle="With hover effect" />
              <CardContent>
                <p className="text-sm text-slate-600">
                  Elevated card with shadow and hover animation.
                </p>
              </CardContent>
            </Card>
          </div>
        </section>
        
        {/* Modal & Tooltips */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Modal & Tooltips</h2>
          <Card>
            <CardContent>
              <div className="flex flex-wrap gap-4">
                <Button onClick={() => setModalOpen(true)}>Open Modal</Button>
                
                <Tooltip content="This is a helpful tooltip">
                  <Button variant="outline">Hover for Tooltip</Button>
                </Tooltip>
                
                <Tooltip content="Edit settings" position="top">
                  <Button variant="ghost">
                    <Settings className="w-4 h-4" />
                  </Button>
                </Tooltip>
              </div>
            </CardContent>
          </Card>
          
          <Modal
            open={modalOpen}
            onClose={() => setModalOpen(false)}
            title="Example Modal"
            size="md"
          >
            <p className="text-slate-700 mb-4">
              This is a modal dialog. It includes proper focus management, keyboard navigation,
              and meets accessibility standards.
            </p>
            <ModalFooter>
              <Button variant="outline" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={() => setModalOpen(false)}>Confirm</Button>
            </ModalFooter>
          </Modal>
        </section>
        
        {/* Table */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Table</h2>
          <Card padding="none">
            <Table striped hoverable>
              <TableHead>
                <TableRow>
                  <TableHeader>Case ID</TableHeader>
                  <TableHeader>Client Name</TableHeader>
                  <TableHeader>Status</TableHeader>
                  <TableHeader>Priority</TableHeader>
                  <TableHeader>Actions</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                <TableRow>
                  <TableCell>#12345</TableCell>
                  <TableCell>John Doe</TableCell>
                  <TableCell><Badge variant="success">Active</Badge></TableCell>
                  <TableCell><Badge variant="warning">High</Badge></TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost"><Edit className="w-4 h-4" /></Button>
                      <Button size="sm" variant="ghost"><Trash2 className="w-4 h-4" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>#12346</TableCell>
                  <TableCell>Jane Smith</TableCell>
                  <TableCell><Badge variant="warning">Pending</Badge></TableCell>
                  <TableCell><Badge variant="info">Normal</Badge></TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost"><Edit className="w-4 h-4" /></Button>
                      <Button size="sm" variant="ghost"><Trash2 className="w-4 h-4" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Card>
        </section>
        
        {/* Tabs */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Tabs</h2>
          <Card>
            <Tabs
              tabs={[
                {
                  id: 'overview',
                  label: 'Overview',
                  content: <p className="text-slate-700">Overview content goes here.</p>
                },
                {
                  id: 'details',
                  label: 'Details',
                  content: <p className="text-slate-700">Detailed information displayed here.</p>
                },
                {
                  id: 'settings',
                  label: 'Settings',
                  content: <p className="text-slate-700">Settings and configuration options.</p>
                },
              ]}
            />
          </Card>
        </section>
        
        {/* Accordion */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Accordion</h2>
          <Accordion
            items={[
              {
                id: '1',
                title: 'What is SimpleTort?',
                content: <p className="text-slate-700">SimpleTort is a comprehensive case management platform for legal professionals.</p>
              },
              {
                id: '2',
                title: 'How do I get started?',
                content: <p className="text-slate-700">Start by creating an account and setting up your first case.</p>
              },
              {
                id: '3',
                title: 'Is my data secure?',
                content: <p className="text-slate-700">Yes, we use industry-standard encryption and follow HIPAA compliance guidelines.</p>
              },
            ]}
          />
        </section>
        
        {/* Progress & Spinner */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Progress & Loading</h2>
          <Card>
            <CardContent>
              <div className="space-y-6">
                <Progress value={75} showLabel label="Upload Progress" />
                <Progress value={50} variant="success" />
                <Progress value={30} variant="warning" />
                <Progress indeterminate />
                
                <Divider />
                
                <div className="flex flex-wrap items-center gap-6">
                  <Spinner size="sm" />
                  <Spinner size="md" />
                  <Spinner size="lg" />
                  <Spinner size="xl" variant="secondary" />
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
        
        {/* Avatar */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Avatar</h2>
          <Card>
            <CardContent>
              <div className="flex flex-wrap items-center gap-6">
                <Avatar initials="JD" />
                <Avatar initials="SM" status="online" />
                <Avatar initials="AB" status="away" size="lg" />
                <Avatar size="xl" />
                <Avatar initials="TC" shape="square" />
              </div>
            </CardContent>
          </Card>
        </section>
        
        {/* Navigation */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Navigation</h2>
          <div className="space-y-6">
            <Card>
              <CardHeader title="Breadcrumb" />
              <CardContent>
                <Breadcrumb
                  items={[
                    { label: 'Home', href: '#' },
                    { label: 'Cases', href: '#' },
                    { label: 'Case #12345' },
                  ]}
                />
              </CardContent>
            </Card>
            
            <Card>
              <CardHeader title="Pagination" />
              <CardContent>
                <Pagination
                  currentPage={currentPage}
                  totalPages={10}
                  onPageChange={setCurrentPage}
                />
              </CardContent>
            </Card>
            
            <Card>
              <CardHeader title="Dropdown Menu" />
              <CardContent>
                <Dropdown
                  trigger={<Button variant="outline">Actions</Button>}
                  items={[
                    { id: '1', label: 'Edit', icon: <Edit className="w-4 h-4" />, onClick: () => {} },
                    { id: '2', label: 'Download', icon: <Download className="w-4 h-4" />, onClick: () => {} },
                    { id: '3', label: 'Delete', icon: <Trash2 className="w-4 h-4" />, onClick: () => {} },
                  ]}
                />
              </CardContent>
            </Card>
          </div>
        </section>
        
        {/* Toast Notifications */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Toast Notifications</h2>
          <Card>
            <CardContent>
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => addToast({ variant: 'success', message: 'Operation completed successfully!' })}>
                  Success Toast
                </Button>
                <Button onClick={() => addToast({ variant: 'error', title: 'Error', message: 'Something went wrong!' })}>
                  Error Toast
                </Button>
                <Button onClick={() => addToast({ variant: 'warning', message: 'Please review your changes' })}>
                  Warning Toast
                </Button>
                <Button onClick={() => addToast({ variant: 'info', message: 'New updates available' })}>
                  Info Toast
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>
        
        {/* Accessibility Notes */}
        <section>
          <h2 className="text-2xl font-bold text-slate-900 mb-6">Accessibility Standards</h2>
          <Card>
            <CardContent>
              <div className="prose prose-slate max-w-none">
                <h3>WCAG 2.1 AA Compliance</h3>
                <p>All components in this design system meet WCAG 2.1 AA accessibility standards:</p>
                <ul>
                  <li><strong>Color Contrast:</strong> All text meets minimum contrast ratio of 4.5:1 (normal text) and 3:1 (large text)</li>
                  <li><strong>Keyboard Navigation:</strong> All interactive components are fully keyboard accessible</li>
                  <li><strong>Focus Indicators:</strong> Visible focus states on all focusable elements</li>
                  <li><strong>ARIA Attributes:</strong> Proper roles, states, and properties for screen readers</li>
                  <li><strong>Semantic HTML:</strong> Correct HTML elements for better accessibility</li>
                  <li><strong>Labels & Descriptions:</strong> All form controls have associated labels</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
      
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}