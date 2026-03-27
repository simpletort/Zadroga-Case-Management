import { Case, Lead } from './types';

export const mockCases: Case[] = [
  {
    id: 'WTC-2024-001',
    clientName: 'John Martinez',
    caseType: 'WTC',
    status: 'Active',
    assignedTo: 'Sarah Johnson',
    medicalScore: 87,
    medicalConfidence: 92,
    createdDate: '2024-01-15',
    lastUpdated: '2026-02-10',
    deadlines: [
      { type: 'WTC Filing', date: '2026-03-15', status: 'safe', daysRemaining: 31 },
      { type: 'Document Collection', date: '2026-02-20', status: 'warning', daysRemaining: 8 }
    ],
    documents: [
      { id: '1', name: 'Medical Records - Primary Care', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-01-20' },
      { id: '2', name: 'Employment Verification Letter', category: 'Employment Verification', status: 'Complete', uploadedDate: '2024-01-18' },
      { id: '3', name: "Driver's License", category: 'ID Documents', status: 'Complete', uploadedDate: '2024-01-16' },
      { id: '4', name: 'Exposure Timeline Documentation', category: 'Exposure Evidence', status: 'Pending' }
    ],
    communications: [
      { id: '1', date: '2026-02-10', type: 'Email', contact: 'John Martinez', subject: 'Document Upload Confirmation', notes: 'Confirmed receipt of medical records' },
      { id: '2', date: '2026-02-08', type: 'Phone', contact: 'John Martinez', subject: 'Case Status Update', notes: 'Discussed next steps and timeline' },
      { id: '3', date: '2026-02-05', type: 'Document Request', contact: 'Dr. Sarah Chen', subject: 'Additional Medical Records', notes: 'Requested pulmonary function test results' }
    ],
    aiSummary: {
      summary: 'Client presents with respiratory complications consistent with WTC exposure. Medical records document chronic rhinosinusitis and reactive airway disease diagnosed in 2003, within the eligible timeframe. Employment verification confirms presence at Ground Zero as construction worker from September 2001 through March 2002.',
      keyFindings: [
        'Documented exposure period: 09/2001 - 03/2002',
        'Primary diagnosis: Chronic rhinosinusitis, Reactive airway disease',
        'First treatment: 06/2003',
        'Employment verified: Construction worker, Turner Construction'
      ],
      medicalConditions: ['Chronic Rhinosinusitis', 'Reactive Airway Disease', 'GERD'],
      confidence: 92,
      processingDate: '2026-02-09'
    }
  },
  {
    id: 'VCF-2024-045',
    clientName: 'Maria Rodriguez',
    caseType: 'VCF',
    status: 'Pending Review',
    assignedTo: 'Michael Chen',
    medicalScore: 94,
    medicalConfidence: 96,
    createdDate: '2024-02-01',
    lastUpdated: '2026-02-11',
    deadlines: [
      { type: 'VCF Submission', date: '2026-02-18', status: 'critical', daysRemaining: 6 },
      { type: 'Medical Review', date: '2026-02-15', status: 'critical', daysRemaining: 3 }
    ],
    documents: [
      { id: '5', name: 'Complete Medical History', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-02-05' },
      { id: '6', name: 'Employment Records - FDNY', category: 'Employment Verification', status: 'Complete', uploadedDate: '2024-02-03' },
      { id: '7', name: 'Social Security Card', category: 'ID Documents', status: 'Complete', uploadedDate: '2024-02-02' },
      { id: '8', name: 'WTC Health Program Enrollment', category: 'Exposure Evidence', status: 'Complete', uploadedDate: '2024-02-06' }
    ],
    communications: [
      { id: '4', date: '2026-02-11', type: 'Email', contact: 'Maria Rodriguez', subject: 'Final Review Before Submission', notes: 'All documents received and verified' },
      { id: '5', date: '2026-02-09', type: 'Meeting', contact: 'Maria Rodriguez', subject: 'Case Review Meeting', notes: 'Reviewed all documentation and prepared submission package' },
      { id: '6', date: '2026-02-06', type: 'Phone', contact: 'VCF Office', subject: 'Submission Requirements', notes: 'Confirmed all requirements met for submission' }
    ],
    aiSummary: {
      summary: 'Former FDNY EMT with extensive WTC exposure during rescue and recovery operations. Medical documentation shows multiple qualifying conditions including asthma, PTSD, and GERD. All conditions certified by WTC Health Program physicians. Strong case with comprehensive medical evidence and clear causal link to 9/11 exposure.',
      keyFindings: [
        'FDNY EMT: 09/11/2001 - 10/15/2001',
        'WTC Health Program enrolled: 2004',
        'Multiple certified conditions',
        'Extensive treatment documentation'
      ],
      medicalConditions: ['Asthma', 'PTSD', 'GERD', 'Chronic Sinusitis'],
      confidence: 96,
      processingDate: '2026-02-10'
    }
  },
  {
    id: 'WTC-2024-032',
    clientName: 'Robert Thompson',
    caseType: 'WTC',
    status: 'Under Review',
    assignedTo: 'Sarah Johnson',
    medicalScore: 76,
    medicalConfidence: 84,
    createdDate: '2024-01-28',
    lastUpdated: '2026-02-09',
    deadlines: [
      { type: 'WTC Filing', date: '2026-04-01', status: 'safe', daysRemaining: 48 },
      { type: 'Document Collection', date: '2026-02-25', status: 'warning', daysRemaining: 13 }
    ],
    documents: [
      { id: '9', name: 'Medical Records - Specialist', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-02-01' },
      { id: '10', name: 'Employment Letter', category: 'Employment Verification', status: 'Pending' },
      { id: '11', name: 'Passport Copy', category: 'ID Documents', status: 'Complete', uploadedDate: '2024-01-29' },
      { id: '12', name: 'Site Access Badge Records', category: 'Exposure Evidence', status: 'Missing' }
    ],
    communications: [
      { id: '7', date: '2026-02-09', type: 'Document Request', contact: 'Former Employer', subject: 'Employment Verification', notes: 'Sent formal request for employment confirmation letter' },
      { id: '8', date: '2026-02-07', type: 'Phone', contact: 'Robert Thompson', subject: 'Missing Documents Discussion', notes: 'Client working on obtaining employment records' }
    ],
    aiSummary: {
      summary: 'Client reports respiratory symptoms following work as cleanup contractor at WTC site. Medical records show diagnosis of chronic bronchitis and sleep apnea. Employment verification pending. Additional documentation needed to establish clear exposure timeline and strengthen case.',
      keyFindings: [
        'Reported exposure: 10/2001 - 12/2001',
        'Diagnosis: Chronic bronchitis (2004), Sleep apnea (2006)',
        'Employment verification: In progress',
        'Additional exposure evidence needed'
      ],
      medicalConditions: ['Chronic Bronchitis', 'Sleep Apnea'],
      confidence: 84,
      processingDate: '2026-02-08'
    }
  },
  {
    id: 'VCF-2024-051',
    clientName: 'Lisa Chang',
    caseType: 'VCF',
    status: 'Active',
    assignedTo: 'Michael Chen',
    medicalScore: 91,
    medicalConfidence: 89,
    createdDate: '2024-02-05',
    lastUpdated: '2026-02-12',
    deadlines: [
      { type: 'VCF Submission', date: '2026-03-10', status: 'safe', daysRemaining: 26 },
      { type: 'Medical Review', date: '2026-02-28', status: 'warning', daysRemaining: 16 }
    ],
    documents: [
      { id: '13', name: 'Complete Medical File', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-02-08' },
      { id: '14', name: 'DOE Employment Records', category: 'Employment Verification', status: 'Complete', uploadedDate: '2024-02-07' },
      { id: '15', name: 'Birth Certificate', category: 'ID Documents', status: 'Complete', uploadedDate: '2024-02-06' },
      { id: '16', name: 'School Attendance Records 2001-2002', category: 'Exposure Evidence', status: 'Complete', uploadedDate: '2024-02-10' }
    ],
    communications: [
      { id: '9', date: '2026-02-12', type: 'Email', contact: 'Lisa Chang', subject: 'Case Progress Update', notes: 'Reviewed AI analysis results and discussed next steps' },
      { id: '10', date: '2026-02-10', type: 'Meeting', contact: 'Lisa Chang', subject: 'Initial Consultation', notes: 'Gathered case information and established timeline' }
    ],
    aiSummary: {
      summary: 'Former teacher at PS 150, located 3 blocks from Ground Zero. School reopened September 2001 with documented air quality issues. Client developed asthma and anxiety disorder. Medical records well-documented. Case presents unique exposure pathway through educational institution reopening.',
      keyFindings: [
        'Teacher at PS 150: 09/2001 - 06/2002',
        'School proximity: 3 blocks from WTC',
        'Asthma diagnosis: 11/2001',
        'Anxiety disorder documented: 2002'
      ],
      medicalConditions: ['Asthma', 'Anxiety Disorder', 'Chronic Sinusitis'],
      confidence: 89,
      processingDate: '2026-02-11'
    }
  },
  {
    id: 'WTC-2024-018',
    clientName: 'David Kim',
    caseType: 'WTC',
    status: 'Submitted',
    assignedTo: 'Sarah Johnson',
    medicalScore: 88,
    medicalConfidence: 93,
    createdDate: '2024-01-20',
    lastUpdated: '2026-02-08',
    deadlines: [
      { type: 'WTC Filing', date: '2026-02-05', status: 'safe', daysRemaining: -7 },
      { type: 'Medical Review', date: '2026-03-01', status: 'safe', daysRemaining: 17 }
    ],
    documents: [
      { id: '17', name: 'Full Medical Records', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-01-25' },
      { id: '18', name: 'Port Authority Employment', category: 'Employment Verification', status: 'Complete', uploadedDate: '2024-01-22' },
      { id: '19', name: 'State ID', category: 'ID Documents', status: 'Complete', uploadedDate: '2024-01-21' },
      { id: '20', name: 'Work Assignment Records', category: 'Exposure Evidence', status: 'Complete', uploadedDate: '2024-01-26' }
    ],
    communications: [
      { id: '11', date: '2026-02-08', type: 'Email', contact: 'David Kim', subject: 'Submission Confirmation', notes: 'Case successfully submitted to WTC Health Program' },
      { id: '12', date: '2026-02-05', type: 'Document Request', contact: 'WTC Health Program', subject: 'Case Submission', notes: 'Submitted complete case package' }
    ],
    aiSummary: {
      summary: 'Port Authority Police Officer with direct exposure during rescue operations on 9/11 and subsequent weeks. Comprehensive medical documentation of respiratory conditions and PTSD. Employment records clearly establish presence and exposure. Excellent case strength with high approval probability.',
      keyFindings: [
        'PAPD Officer: 09/11/2001 - 10/30/2001',
        'First responder status confirmed',
        'Multiple certified conditions',
        'Complete documentation package'
      ],
      medicalConditions: ['Chronic Rhinosinusitis', 'PTSD', 'Reactive Airway Disease'],
      confidence: 93,
      processingDate: '2026-02-07'
    }
  },
  {
    id: 'VCF-2024-039',
    clientName: 'Jennifer Wilson',
    caseType: 'VCF',
    status: 'Active',
    assignedTo: 'Michael Chen',
    medicalScore: 82,
    medicalConfidence: 87,
    createdDate: '2024-01-30',
    lastUpdated: '2026-02-11',
    deadlines: [
      { type: 'VCF Submission', date: '2026-03-20', status: 'safe', daysRemaining: 36 },
      { type: 'Document Collection', date: '2026-02-22', status: 'warning', daysRemaining: 10 }
    ],
    documents: [
      { id: '21', name: 'Medical Records Package', category: 'Medical Records', status: 'Complete', uploadedDate: '2024-02-03' },
      { id: '22', name: 'Office Building Lease Records', category: 'Employment Verification', status: 'Complete', uploadedDate: '2024-02-01' },
      { id: '23', name: 'Driver\'s License', category: 'ID Documents', status: 'Complete', uploadedDate: '2024-01-31' },
      { id: '24', name: 'Office Entry Logs', category: 'Exposure Evidence', status: 'Pending' }
    ],
    communications: [
      { id: '13', date: '2026-02-11', type: 'Phone', contact: 'Jennifer Wilson', subject: 'Document Follow-up', notes: 'Discussed obtaining office entry logs from building management' },
      { id: '14', date: '2026-02-08', type: 'Email', contact: 'Jennifer Wilson', subject: 'Medical Records Received', notes: 'Confirmed receipt of all medical documentation' }
    ],
    aiSummary: {
      summary: 'Office worker at 7 World Trade Center. Building sustained damage and was evacuated on 9/11. Returned to work in temporary location with documented exposure to dust and debris. Developed respiratory conditions. Additional exposure evidence would strengthen case.',
      keyFindings: [
        'Worked at 7 WTC: Pre-9/11 through 2002',
        'Building evacuated on 9/11',
        'Respiratory symptoms onset: 2002',
        'Additional exposure evidence recommended'
      ],
      medicalConditions: ['Asthma', 'Chronic Sinusitis'],
      confidence: 87,
      processingDate: '2026-02-10'
    }
  }
];

// Mock Leads Data
export const mockLeads: Lead[] = [
  {
    id: 'LEAD-001',
    firstName: 'Sarah',
    lastName: 'Anderson',
    email: 'sarah.anderson@email.com',
    phone: '(555) 123-4567',
    address: '123 Main St',
    city: 'New York',
    state: 'NY',
    zipCode: '10001',
    dateOfBirth: '1975-03-15',
    status: 'qualified',
    source: 'SLG',
    createdAt: '2026-02-18T10:30:00Z',
    updatedAt: '2026-02-19T14:20:00Z',
    exposureLocation: 'Ground Zero - Construction Worker',
    exposureStartDate: '2001-09-15',
    exposureEndDate: '2002-03-30',
    injuryDescription: 'Chronic respiratory issues, persistent cough, and sinusitis developed after working at Ground Zero cleanup operations.',
    medicalDocuments: ['Chest X-Ray Report.pdf', 'Pulmonary Function Test.pdf'],
    assignedTo: 'Sarah Johnson',
    vcfScreening: {
      score: 89,
      qualified: true,
      confidence: 'high',
      screenedAt: '2026-02-19T09:15:00Z',
      criteria: [
        {
          name: 'Presence at Exposure Zone',
          description: 'Confirmed presence at WTC site during eligible period',
          met: true,
          weight: 30,
          notes: 'Employment records confirm 6+ months at Ground Zero'
        },
        {
          name: 'Qualifying Medical Condition',
          description: 'Diagnosed with VCF-eligible medical condition',
          met: true,
          weight: 40,
          notes: 'Chronic rhinosinusitis and reactive airway disease documented'
        },
        {
          name: 'Timeline Consistency',
          description: 'Medical diagnosis within acceptable timeframe after exposure',
          met: true,
          weight: 20,
          notes: 'First symptoms reported in 2003, within eligible window'
        },
        {
          name: 'Documentation Completeness',
          description: 'Sufficient medical and exposure documentation provided',
          met: true,
          weight: 10,
          notes: 'Medical records and employment verification complete'
        }
      ]
    }
  },
  {
    id: 'LEAD-002',
    firstName: 'Michael',
    lastName: 'Torres',
    email: 'm.torres@email.com',
    phone: '(555) 234-5678',
    address: '456 Broadway Ave',
    city: 'New York',
    state: 'NY',
    zipCode: '10012',
    dateOfBirth: '1968-07-22',
    status: 'new',
    source: 'Shapiro Law Group',
    createdAt: '2026-02-20T08:45:00Z',
    updatedAt: '2026-02-20T08:45:00Z',
    exposureLocation: 'Lower Manhattan Resident',
    exposureStartDate: '2001-09-11',
    exposureEndDate: '2002-06-30',
    injuryDescription: 'Developed asthma and anxiety after living 2 blocks from WTC site during cleanup period.',
    medicalDocuments: ['Medical History Summary.pdf']
  },
  {
    id: 'LEAD-003',
    firstName: 'Jennifer',
    lastName: 'Patel',
    email: 'jpatel@email.com',
    phone: '(555) 345-6789',
    address: '789 Park Place',
    city: 'Brooklyn',
    state: 'NY',
    zipCode: '11201',
    dateOfBirth: '1982-11-08',
    status: 'contacted',
    source: 'Direct',
    createdAt: '2026-02-19T15:20:00Z',
    updatedAt: '2026-02-20T11:30:00Z',
    exposureLocation: 'Financial District Office Worker',
    exposureStartDate: '2001-09-20',
    exposureEndDate: '2002-12-31',
    injuryDescription: 'Chronic sinusitis and GERD following return to office near WTC site.',
    vcfScreening: {
      score: 67,
      qualified: false,
      confidence: 'medium',
      screenedAt: '2026-02-20T10:00:00Z',
      criteria: [
        {
          name: 'Presence at Exposure Zone',
          description: 'Confirmed presence at WTC site during eligible period',
          met: true,
          weight: 30,
          notes: 'Office located in Financial District'
        },
        {
          name: 'Qualifying Medical Condition',
          description: 'Diagnosed with VCF-eligible medical condition',
          met: true,
          weight: 40,
          notes: 'Chronic sinusitis documented'
        },
        {
          name: 'Timeline Consistency',
          description: 'Medical diagnosis within acceptable timeframe after exposure',
          met: false,
          weight: 20,
          notes: 'First diagnosis in 2008 - may exceed eligible window'
        },
        {
          name: 'Documentation Completeness',
          description: 'Sufficient medical and exposure documentation provided',
          met: false,
          weight: 10,
          notes: 'Additional medical records needed'
        }
      ],
      redFlags: [
        'Medical diagnosis timeline may be outside eligible window',
        'Limited medical documentation provided'
      ]
    }
  },
  {
    id: 'LEAD-004',
    firstName: 'Robert',
    lastName: 'Johnson',
    email: 'robert.j@email.com',
    phone: '(555) 456-7890',
    address: '321 5th Avenue',
    city: 'New York',
    state: 'NY',
    zipCode: '10016',
    dateOfBirth: '1970-01-30',
    status: 'qualified',
    source: 'SLG',
    createdAt: '2026-02-17T13:10:00Z',
    updatedAt: '2026-02-19T16:45:00Z',
    exposureLocation: 'FDNY First Responder',
    exposureStartDate: '2001-09-11',
    exposureEndDate: '2001-10-15',
    injuryDescription: 'PTSD, asthma, and chronic respiratory conditions from 9/11 rescue operations.',
    medicalDocuments: ['FDNY Medical Records.pdf', 'PTSD Evaluation.pdf', 'Respiratory Tests.pdf'],
    assignedTo: 'Michael Chen',
    vcfScreening: {
      score: 96,
      qualified: true,
      confidence: 'high',
      screenedAt: '2026-02-18T14:30:00Z',
      criteria: [
        {
          name: 'Presence at Exposure Zone',
          description: 'Confirmed presence at WTC site during eligible period',
          met: true,
          weight: 30,
          notes: 'FDNY first responder with verified service records'
        },
        {
          name: 'Qualifying Medical Condition',
          description: 'Diagnosed with VCF-eligible medical condition',
          met: true,
          weight: 40,
          notes: 'Multiple certified conditions: PTSD, asthma, chronic rhinosinusitis'
        },
        {
          name: 'Timeline Consistency',
          description: 'Medical diagnosis within acceptable timeframe after exposure',
          met: true,
          weight: 20,
          notes: 'WTC Health Program certified conditions'
        },
        {
          name: 'Documentation Completeness',
          description: 'Sufficient medical and exposure documentation provided',
          met: true,
          weight: 10,
          notes: 'Comprehensive medical documentation from WTC Health Program'
        }
      ]
    }
  },
  {
    id: 'LEAD-005',
    firstName: 'Emily',
    lastName: 'Chen',
    email: 'emily.chen@email.com',
    phone: '(555) 567-8901',
    address: '555 West End Ave',
    city: 'New York',
    state: 'NY',
    zipCode: '10024',
    status: 'disqualified',
    source: 'Direct',
    createdAt: '2026-02-16T09:30:00Z',
    updatedAt: '2026-02-18T10:15:00Z',
    exposureLocation: 'Midtown Office',
    exposureStartDate: '2001-11-01',
    exposureEndDate: '2002-05-30',
    injuryDescription: 'General respiratory complaints.',
    vcfScreening: {
      score: 32,
      qualified: false,
      confidence: 'low',
      screenedAt: '2026-02-17T11:00:00Z',
      criteria: [
        {
          name: 'Presence at Exposure Zone',
          description: 'Confirmed presence at WTC site during eligible period',
          met: false,
          weight: 30,
          notes: 'Midtown location outside designated exposure zone'
        },
        {
          name: 'Qualifying Medical Condition',
          description: 'Diagnosed with VCF-eligible medical condition',
          met: false,
          weight: 40,
          notes: 'No VCF-qualifying diagnosis provided'
        },
        {
          name: 'Timeline Consistency',
          description: 'Medical diagnosis within acceptable timeframe after exposure',
          met: false,
          weight: 20,
          notes: 'No medical records provided'
        },
        {
          name: 'Documentation Completeness',
          description: 'Sufficient medical and exposure documentation provided',
          met: false,
          weight: 10,
          notes: 'Insufficient documentation'
        }
      ],
      redFlags: [
        'Location outside designated exposure zone',
        'No qualifying medical diagnosis',
        'Insufficient documentation provided'
      ]
    }
  },
  {
    id: 'LEAD-006',
    firstName: 'David',
    lastName: 'Martinez',
    email: 'dmartinez@email.com',
    phone: '(555) 678-9012',
    address: '888 Canal St',
    city: 'New York',
    state: 'NY',
    zipCode: '10013',
    dateOfBirth: '1979-05-18',
    status: 'new',
    source: 'Shapiro Law Group',
    createdAt: '2026-02-20T14:25:00Z',
    updatedAt: '2026-02-20T14:25:00Z',
    exposureLocation: 'Tribeca Resident',
    exposureStartDate: '2001-09-11',
    exposureEndDate: '2002-08-31',
    injuryDescription: 'Asthma and chronic cough developed after exposure to WTC dust cloud.',
    medicalDocuments: ['Asthma Diagnosis.pdf']
  },
  {
    id: 'LEAD-007',
    firstName: 'Lisa',
    lastName: 'Brown',
    email: 'l.brown@email.com',
    phone: '(555) 789-0123',
    address: '999 Greenwich St',
    city: 'New York',
    state: 'NY',
    zipCode: '10014',
    dateOfBirth: '1973-09-25',
    status: 'contacted',
    source: 'SLG',
    createdAt: '2026-02-19T11:40:00Z',
    updatedAt: '2026-02-20T09:20:00Z',
    exposureLocation: 'PS 234 Teacher',
    exposureStartDate: '2001-10-01',
    exposureEndDate: '2002-06-30',
    injuryDescription: 'Developed asthma and anxiety working at school near Ground Zero.',
    medicalDocuments: ['School Employment.pdf', 'Medical Records.pdf'],
    assignedTo: 'Sarah Johnson',
    vcfScreening: {
      score: 78,
      qualified: true,
      confidence: 'medium',
      screenedAt: '2026-02-20T08:30:00Z',
      criteria: [
        {
          name: 'Presence at Exposure Zone',
          description: 'Confirmed presence at WTC site during eligible period',
          met: true,
          weight: 30,
          notes: 'School located within exposure zone'
        },
        {
          name: 'Qualifying Medical Condition',
          description: 'Diagnosed with VCF-eligible medical condition',
          met: true,
          weight: 40,
          notes: 'Asthma diagnosis documented'
        },
        {
          name: 'Timeline Consistency',
          description: 'Medical diagnosis within acceptable timeframe after exposure',
          met: true,
          weight: 20,
          notes: 'Diagnosis in 2002 within eligible window'
        },
        {
          name: 'Documentation Completeness',
          description: 'Sufficient medical and exposure documentation provided',
          met: false,
          weight: 10,
          notes: 'Additional medical records recommended'
        }
      ]
    }
  },
  {
    id: 'LEAD-008',
    firstName: 'James',
    lastName: 'Wilson',
    email: 'james.w@email.com',
    phone: '(555) 890-1234',
    address: '111 Liberty St',
    city: 'New York',
    state: 'NY',
    zipCode: '10006',
    status: 'converted',
    source: 'Direct',
    createdAt: '2026-02-15T10:00:00Z',
    updatedAt: '2026-02-18T15:30:00Z',
    exposureLocation: 'Port Authority Police',
    exposureStartDate: '2001-09-11',
    exposureEndDate: '2001-11-30',
    injuryDescription: 'Multiple respiratory conditions and PTSD from first responder duties.',
    medicalDocuments: ['PAPD Records.pdf', 'Complete Medical File.pdf'],
    assignedTo: 'Michael Chen',
    notes: 'Converted to case VCF-2024-067 on 2026-02-18'
  }
];