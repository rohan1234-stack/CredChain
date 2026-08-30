# 🔐 CredChain

### Student-Owned Academic Credential Passport

CredChain is a secure, full-stack platform for issuing, owning, sharing,
and verifying academic credentials.

It connects students, educational institutions, and companies through
cryptographically signed credentials, controlled sharing, deterministic
eligibility evaluation, document workflows, notifications, and
timestamped application history.

## 🚀 Live Demo

**[Open CredChain Live Demo](https://cred-chain-five.vercel.app/)**

---

## 📌 About

CredChain addresses a common problem in academic and recruitment
workflows: academic credentials are often distributed as static
documents that are difficult to verify, difficult to share securely,
and disconnected from recruitment workflows.

CredChain turns academic credentials into structured digital records
that can be:

- 🎓 Issued by verified institutions
- 🔐 Cryptographically signed by the issuing institution
- 👤 Owned and controlled by students
- 🤝 Shared selectively with companies and verifiers
- 🔎 Independently verified
- 📄 Linked to their original supporting documents
- ⏱️ Tracked through timestamped workflows
- 💼 Used for deterministic job-eligibility evaluation

---

# 👥 Platform Roles

### 🎓 Students

Students manage their academic credentials, control access to shared
credentials, request credentials from institutions, and apply for jobs.

### 🏛️ Institutions

Institutions manage students, review credential requests, issue
credentials, upload supporting documents, and cryptographically sign
credential records.

### 💼 Companies / Verifiers

Companies create jobs, review applications, access shared credentials,
and verify credential authenticity, status, and access permissions.

---

# ✨ Key Features

## 🎓 Student Portal

- Student dashboard
- Academic credential wallet
- Credential details and verification status
- Original document viewing
- Document upload and review
- Global institution and company discovery
- Job discovery
- Deterministic eligibility evaluation
- Degree, CGPA, and graduation-year matching
- Job applications
- Duplicate application protection
- Application status history
- Timestamped application timelines
- AI-assisted job analysis
- Credential sharing
- Share links and QR workflows
- Share expiry and revocation
- Notifications
- Activity history
- Institution credential requests
- Credential-request timelines

---

## 🏛️ Institution Portal

- Institution dashboard
- Student management
- Credential issuance
- Academic credential metadata
- Document upload and review
- Certificate requests
- Request approval and rejection
- Approve & Issue workflow
- Credential signing
- Credential revocation
- Timestamped request history
- Institution activity history
- Notification center
- Secure private document storage

---

## 💼 Company / Verifier Portal

- Company dashboard
- Job creation and management
- Candidate applications
- Application status management
- Application timelines and timestamps
- Credential requests
- Shared credential review
- Credential verification
- Candidate eligibility information
- Notifications
- Activity history
- Credential type mismatch detection
- Revocation-aware credential access

---

# 🔐 Credential Security

When a credential is issued, CredChain creates a canonical credential
payload containing structured information such as:

- Credential identifier
- Student identifier
- Student name
- Institution identifier
- Institution name
- Credential type
- Credential title
- Degree
- Graduation year
- CGPA
- Document hash
- Issuance timestamp

The institution signs this canonical payload using its signing key.

During verification, the backend reconstructs the canonical payload and
verifies the digital signature.

This allows CredChain to detect changes to the signed credential metadata
after issuance.

---

# 📄 Document Integrity

CredChain associates the original uploaded document with a SHA-256 hash.

During verification:

1. The stored document is retrieved.
2. Its current bytes are hashed.
3. The resulting hash is compared with the hash recorded at issuance.

### What "Document Unaltered" proves

It proves that the retrieved document is the same file represented by
the hash recorded when the credential was issued.

### What it does not currently prove

CredChain does **not** currently perform automatic OCR, PDF text
extraction, or PDF-content-to-metadata matching.

For example, the system does not automatically determine whether the
student name or CGPA printed inside a PDF matches the structured
credential metadata.

This keeps the cryptographic verification guarantees precise and
avoids overstating what document verification proves.

---

# 🤝 Controlled Credential Sharing

Students control access to their credentials through share grants.

A share can define:

- Intended recipient
- Permission level
- Expiry
- Credential reference
- Access state

Students can revoke previously granted access.

Revocation changes whether the recipient is currently authorized while
preserving the associated historical activity.

---

# 💼 Job Application Workflow

CredChain connects academic credentials with recruitment workflows.

A typical successful application lifecycle is:

```text
APPLIED
   ↓
UNDER_REVIEW
   ↓
SHORTLISTED
   ↓
ACCEPTED
