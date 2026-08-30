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

This allows CredChain to detect changes to signed credential metadata
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
```

Applications can also move through valid terminal outcomes such as:

```text
REJECTED
WITHDRAWN
```

Application transitions are recorded in the activity history so users
can see the actual workflow rather than only the latest status.

CredChain also prevents duplicate job applications for the same student
and job.

---

# ⏱️ Timestamped Workflow History

CredChain provides timestamped workflow timelines for important actions.

### Certificate Request

```text
REQUESTED
    ↓
APPROVED
    ↓
FULFILLED
```

or:

```text
REQUESTED
    ↓
REJECTED
```

### Job Application

```text
APPLIED
    ↓
UNDER_REVIEW
    ↓
SHORTLISTED
    ↓
ACCEPTED
```

with valid rejection and withdrawal paths.

The timelines are based on recorded workflow events and display actual
timestamps for states that were reached. The system does not fabricate
timestamps for states that never occurred.

---

# ✅ Deterministic Eligibility

Eligibility is calculated by the backend using trusted structured
credential metadata.

The system evaluates criteria such as:

- Degree
- CGPA
- Graduation year

Example:

```text
Credential CGPA: 9.6
Job minimum CGPA: 5.0

→ CGPA requirement: PASS
```

The eligibility engine is deterministic and rule-based.

AI assistance does not replace the deterministic eligibility decision.

---

# 🤖 AI-Assisted Analysis

CredChain supports AI-assisted analysis for:

- Job requirement extraction
- Required-document analysis
- Company intelligence
- Credential/job matching assistance

The production deployment uses the configured Groq provider when
`AI_ENABLED=true`.

AI acts as an assistance layer; the final deterministic eligibility
decision remains backend-driven.

---

# 🔎 Credential Verification

Credential verification evaluates multiple independent signals.

### 1. Issuer Identity

Confirms that the issuing institution is registered and has the
cryptographic information required for verification.

### 2. Digital Signature

Verifies that the credential's signed metadata matches what was issued.

### 3. Document Unaltered

Verifies that the retrieved document matches the document hash recorded
at issuance.

### 4. Credential Status

Checks whether the credential is currently active or has been revoked.

### 5. Access Authorization

Confirms that the requesting viewer has permission to access the
credential.

### 6. Credential Type Matching

Detects when the credential being presented does not match the credential
type originally requested.

---

# 🗂️ Document Storage

CredChain uses private Supabase Storage for application documents.

Credential documents are stored in the private:

```text
credential-documents
```

bucket using credential-specific object paths.

Student-uploaded documents are stored in the private:

```text
student-documents
```

bucket using student-document-specific object paths.

Private storage is accessed through the backend using server-side
credentials and application authorization.

The Supabase service-role credential is never exposed to the frontend.

---

# 🧱 System Architecture

```text
┌───────────────────────────┐
│      React Frontend       │
│     TypeScript + Vite     │
└─────────────┬─────────────┘
              │
              │ REST API
              ▼
┌───────────────────────────┐
│       FastAPI Backend     │
│                           │
│ Authentication            │
│ Authorization             │
│ Credential Issuance       │
│ Verification              │
│ Eligibility               │
│ Job Applications          │
│ Notifications             │
│ Activity Logging          │
└─────────────┬─────────────┘
              │
       ┌──────┴─────────┐
       ▼                ▼
┌──────────────┐  ┌──────────────────┐
│  PostgreSQL  │  │ Supabase Storage │
│   Database   │  │ Private Documents│
└──────────────┘  └──────────────────┘
```

Supporting platform components include:

- JWT-based authentication
- Role-based authorization
- Ed25519 credential signing
- SHA-256 document hashing
- Activity logging
- Notification workflows
- Controlled credential sharing
- Organization directory
- AI-assisted analysis

---

# 🔐 Security Principles

CredChain is designed around:

- Server-side authorization
- Role-based access boundaries
- Student ownership checks
- Institution ownership checks
- Company ownership checks
- Cryptographic credential signing
- Document hashing
- Private document storage
- Share-grant authorization
- Share revocation
- Activity logging
- Duplicate job-application protection
- Safe storage failure handling
- Backend-only service credentials

Sensitive deployment values are supplied through environment
configuration rather than committed into the frontend application.

---

# 🌐 Organization Directory

CredChain supports discovery of institutions and companies through a
global organization directory.

The directory supports:

- Institution search
- Company search
- Name-based discovery
- Signup organization selection
- Directory-only organizations
- Registered organization accounts

See:

**[docs/DIRECTORY.md](docs/DIRECTORY.md)**

for directory architecture, data sources, and import information.

---

# 🔔 Notifications and Activity

CredChain provides notification and activity workflows across important
events such as:

- Credential requests
- Credential issuance
- Credential sharing
- Share revocation
- Job applications
- Application status changes

Activity history complements workflow timelines by preserving the record
of relevant system events.

---

# 🧪 Validation

The project has been validated using:

- TypeScript compilation
- Production frontend builds
- ESLint
- Python static analysis with Pyflakes
- Backend test collection
- Targeted backend logic validation
- Production smoke testing of major workflows

Some backend tests require a local PostgreSQL environment for full
execution.

---

# 🚀 Deployment

### Frontend

**Vercel**

https://cred-chain-five.vercel.app/

### Backend

**Render**

https://credchain-backend-wg6v.onrender.com

The frontend communicates with the deployed backend through
environment-configured API settings.

---

# 📚 Documentation

Additional project documentation is available in:

```text
docs/
```

including the organization directory documentation.

---

# 🎯 Project Goal

CredChain aims to make academic credentials:

**Authentic. Portable. Verifiable. Shareable. Auditable.**

Instead of treating an academic credential as only a PDF, CredChain
connects the credential with the broader academic and recruitment
workflow:

```text
Institution
    ↓
Cryptographic Issuance
    ↓
Student Ownership
    ↓
Controlled Sharing
    ↓
Company Verification
    ↓
Eligibility Evaluation
    ↓
Job Application
    ↓
Application Workflow
    ↓
Timestamped Audit History
```

---

# 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript + Vite |
| Backend | FastAPI + Python |
| Database | PostgreSQL |
| Authentication | JWT-based authentication |
| Credential Signing | Ed25519 |
| Document Hashing | SHA-256 |
| Document Storage | Supabase Storage |
| AI Assistance | Groq |
| Frontend Hosting | Vercel |
| Backend Hosting | Render |

---

## 🔗 Live Application

**[🚀 Open CredChain](https://cred-chain-five.vercel.app/)**

---

## 📌 Project Status

**Production-ready project build**

The current implementation includes credential issuance, cryptographic
verification, private document storage, controlled sharing,
deterministic eligibility evaluation, job applications, notifications,
and timestamped workflow history.
