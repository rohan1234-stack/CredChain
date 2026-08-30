import {
  LayoutGrid,
  Wallet,
  Briefcase,
  Building2,
  Landmark,
  Inbox,
  Activity,
  Users,
  FileCheck2,
  Share2,
  ClipboardList,
  ShieldQuestion,
  FileStack,
  ShieldCheck,
} from 'lucide-react'
import type { Role } from '../../types'
import type { LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: number
}

export const NAV_CONFIG: Record<Role, { primary: NavItem[]; secondary: NavItem[] }> = {
  student: {
    primary: [
      { to: '/student', label: 'Dashboard', icon: LayoutGrid },
      { to: '/student/credentials', label: 'Credentials', icon: Wallet },
      { to: '/student/jobs', label: 'Jobs', icon: Briefcase },
      { to: '/student/my-applications', label: 'My Applications', icon: FileStack },
      { to: '/student/institutions', label: 'Institutions', icon: Landmark },
      { to: '/student/companies', label: 'Companies', icon: Building2 },
      { to: '/student/requests', label: 'Incoming Requests', icon: Inbox },
      { to: '/student/certificate-requests', label: 'Request from Institution', icon: ClipboardList },
      { to: '/student/documents', label: 'Upload for Review', icon: ShieldQuestion },
      { to: '/student/shares', label: 'My Shares', icon: Share2 },
      { to: '/student/activity', label: 'Activity', icon: Activity },
    ],
    secondary: [],
  },
  institution: {
    primary: [
      { to: '/institution', label: 'Dashboard', icon: LayoutGrid },
      { to: '/institution/students', label: 'Students', icon: Users },
      { to: '/institution/credentials', label: 'Credentials', icon: FileCheck2 },
      { to: '/institution/certificate-requests', label: 'Certificate Requests', icon: ClipboardList },
      { to: '/institution/documents', label: 'Document Verification', icon: ShieldQuestion },
      { to: '/institution/activity', label: 'Activity', icon: Activity },
    ],
    secondary: [],
  },
  verifier: {
    primary: [
      { to: '/verifier', label: 'Dashboard', icon: LayoutGrid },
      { to: '/verifier/profile', label: 'Company Profile', icon: Building2 },
      { to: '/verifier/jobs', label: 'Jobs', icon: Briefcase },
      { to: '/verifier/applications', label: 'Applications', icon: FileStack },
      { to: '/verifier/requests', label: 'Requests', icon: Inbox },
      { to: '/verifier/activity', label: 'Activity', icon: Activity },
    ],
    secondary: [],
  },
  admin: {
    primary: [{ to: '/admin', label: 'Verification', icon: ShieldCheck }],
    secondary: [],
  },
}
