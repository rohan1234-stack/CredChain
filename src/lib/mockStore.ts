// ---------------------------------------------------------------------------
// In-memory mock data store.
//
// This simulates a backend for the hackathon demo. Every "mutation" (issue,
// revoke, share, approve/decline, tamper) writes into these arrays, and
// every read goes through src/lib/api.ts. When the real backend is ready,
// only api.ts needs to change — no component should import this file
// directly.
// ---------------------------------------------------------------------------

import type {
  User,
  Credential,
  CredentialRequest,
  AccessLogEntry,
} from '../types'

export const users: User[] = [
  { id: 'u-rahul', name: 'Rahul Kumar', initials: 'RK', role: 'student' },
  { id: 'u-anjali', name: 'Anjali Mehta', initials: 'AM', role: 'verifier', orgName: 'ABC Technologies' },
  { id: 'u-iyer', name: 'Prof. S. Iyer', initials: 'SI', role: 'institution', orgName: 'XYZ University' },
]

export const credentials: Credential[] = [
  {
    id: 'cred-degree',
    type: 'degree',
    title: 'B.Tech Computer Science',
    issuer: 'XYZ University',
    issuedTo: 'u-rahul',
    issuedDate: '2026',
    status: 'verified',
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'XYZ University' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Degree', value: 'B.Tech Computer Science' },
      { label: 'Graduation', value: '2026' },
    ],
  },
  {
    id: 'cred-transcript',
    type: 'transcript',
    title: 'Final Transcript',
    issuer: 'XYZ University',
    issuedTo: 'u-rahul',
    issuedDate: '2026',
    status: 'verified',
    cgpa: 8.7,
    originalCgpa: 8.7,
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'XYZ University' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Degree', value: 'B.Tech Computer Science' },
      { label: 'Graduation', value: '2026' },
      { label: 'CGPA', value: '8.7' },
    ],
  },
  {
    id: 'cred-migration',
    type: 'migration',
    title: 'Migration Certificate',
    issuer: 'XYZ University',
    issuedTo: 'u-rahul',
    issuedDate: '2026',
    status: 'verified',
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'XYZ University' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Type', value: 'Migration Certificate' },
      { label: 'Issued', value: '2026' },
    ],
  },
  {
    id: 'cred-internship',
    type: 'internship',
    title: 'Internship Certificate',
    issuer: 'ABC Technologies',
    issuedTo: 'u-rahul',
    issuedDate: '2025',
    status: 'verified',
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'ABC Technologies' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Role', value: 'Software Engineering Intern' },
      { label: 'Issued', value: '2025' },
    ],
  },
  {
    id: 'cred-sql',
    type: 'certification',
    title: 'SQL Certification',
    issuer: 'Coursera',
    issuedTo: 'u-rahul',
    issuedDate: '2025',
    status: 'verified',
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'Coursera' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Certification', value: 'SQL' },
      { label: 'Issued', value: '2025' },
    ],
  },
  {
    id: 'cred-cloud',
    type: 'course',
    title: 'Cloud Fundamentals',
    issuer: 'AWS Academy',
    issuedTo: 'u-rahul',
    issuedDate: '2024',
    status: 'pending',
    documentUrl: '#',
    fields: [
      { label: 'Issued by', value: 'AWS Academy' },
      { label: 'Student', value: 'Rahul Kumar' },
      { label: 'Course', value: 'Cloud Fundamentals' },
      { label: 'Issued', value: '2024' },
    ],
  },
]

export const credentialRequests: CredentialRequest[] = [
  {
    id: 'req-1',
    requesterOrg: 'ABC Technologies',
    requesterRole: 'Software Engineer Application',
    credentialIds: ['cred-degree', 'cred-transcript'],
    status: 'pending',
    requestedAt: 'Today, 10:31 AM',
  },
]

export const accessLog: AccessLogEntry[] = [
  {
    id: 'log-1',
    category: 'verification',
    label: 'Credential Verified',
    actor: 'ABC Technologies',
    action: 'Transcript verified',
    timestamp: '10:42 AM',
    icon: 'verified',
  },
  {
    id: 'log-2',
    category: 'requests',
    label: 'Credential Request Created',
    actor: 'ABC Technologies',
    action: 'Credential request received',
    timestamp: '10:31 AM',
    icon: 'request',
  },
  {
    id: 'log-3',
    category: 'sharing',
    label: 'Credential Shared',
    actor: 'XYZ University',
    action: 'Degree shared',
    timestamp: 'Yesterday',
    icon: 'shared',
  },
]

export const institutionActivity: AccessLogEntry[] = [
  {
    id: 'iact-1',
    category: 'verification',
    label: 'Credential Verified',
    actor: 'ABC Technologies',
    action: 'Final Transcript verified',
    timestamp: '10:42 AM',
    icon: 'verified',
  },
  {
    id: 'iact-2',
    category: 'credential',
    label: 'Credential Issued',
    actor: 'Rahul Kumar',
    action: 'Migration Certificate issued',
    timestamp: 'Yesterday',
    icon: 'issued',
  },
]

