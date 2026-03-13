export interface AISummary {
  summary: string;
  keyFindings: string[];
  medicalConditions: string[];
  confidence: number;
  processingDate: string;
}

// Lead Management Types
export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'disqualified' | 'converted';
export type LeadSource = 'website' | 'referral' | 'phone' | 'email' | 'social';

export interface Lead {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  address: string;
  city: string;
  state: string;
  zipCode: string;
  dateOfBirth?: string;
  status: LeadStatus;
  source: LeadSource;
  createdAt: string;
  updatedAt: string;
  
  // VCF-specific fields
  exposureLocation: string;
  exposureStartDate: string;
  exposureEndDate: string;
  injuryDescription: string;
  medicalDocuments?: string[];
  
  // VCF Screening
  vcfScreening?: VCFScreening;
  
  // Assignment
  assignedTo?: string;
  
  // Notes
  notes?: string;
}

export interface VCFScreening {
  score: number; // 0-100
  qualified: boolean;
  confidence: 'low' | 'medium' | 'high';
  screenedAt: string;
  criteria: ScreeningCriterion[];
  redFlags?: string[];
}

export interface ScreeningCriterion {
  name: string;
  description: string;
  met: boolean;
  weight: number;
  notes?: string;
}