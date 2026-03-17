/**
 * TypeScript Type Definitions
 * Matches backend API schemas
 */

// ==========================================
// API REQUEST/RESPONSE TYPES
// ==========================================

export interface ResearchRequest {
  query: string;
}

export interface ResearchResponse {
  job_id: string;
  status: string;
}

export interface JobStatus {
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_node?: string;
  error_message?: string;
}

export interface JobArtifacts {
  markdown_url?: string;
  chart_data_url?: string;
}

// ==========================================
// CHART DATA TYPES (Recharts compatible)
// ==========================================

export interface ChartDataPoint {
  name: string;
  value: number;
  [key: string]: string | number;  // Allow additional properties
}

export interface ChartData {
  title: string;
  type: 'line' | 'bar' | 'area' | 'scatter' | 'pie';
  data: ChartDataPoint[];
  xAxisKey?: string;
  yAxisKey?: string;
  description?: string;
}

// ==========================================
// CHAT/CLARIFICATION TYPES
// ==========================================

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export interface ClarifyingQuestion {
  id: string;
  question: string;
  type: 'text' | 'select' | 'multiselect';
  options?: string[];
}

// ==========================================
// USER/SESSION TYPES
// ==========================================

export interface User {
  id: string;
  email: string;
  name?: string;
}

// TODO: Add more types as needed
