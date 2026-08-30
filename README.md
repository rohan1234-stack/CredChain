# 🔐 CredChain

### Student-Owned Academic Credential Passport

## 🚀 Live Demo

**[Open CredChain Live Demo](https://cred-chain-five.vercel.app)**

## 📌 About

CredChain is a student-owned academic credential passport that allows students
to securely receive, own, share, and verify academic credentials.

The platform provides dedicated experiences for:

- 🎓 Students
- 🏛️ Institutions
- 💼 Companies / Verifiers

CredChain uses a real full-stack architecture with a React frontend, FastAPI
backend, PostgreSQL database, authentication, credential signing and
verification, document workflows, eligibility evaluation, credential sharing,
and AI-assisted analysis.

## ✨ Key Features

### 🎓 Student Portal

- Student dashboard
- Academic credential wallet
- Credential details and verification status
- Document upload and review
- Global institution & company discovery (see [docs/DIRECTORY.md](docs/DIRECTORY.md) for the directory architecture, data sources, and import commands)
- Job discovery
- Deterministic eligibility evaluation
- CGPA, degree, and graduation-year matching
- Job applications
- AI-assisted job analysis
- Credential sharing
- QR/share-link workflows
- Activity history

### 🏛️ Institution Portal

- Institution dashboard
- Student management
- Credential issuance
- Academic credential metadata
- Document review and approval
- Credential requests
- Credential signing
- Credential revocation
- Institution activity history

### 💼 Company / Verifier Portal

- Company dashboard
- Job creation and management
- Candidate applications
- Credential requests
- Credential verification
- VERIFIED / REVOKED / TYPE_MISMATCH verification states
- Shared credential review
- Candidate eligibility information

### 🤖 AI-Assisted Analysis

CredChain supports AI-assisted analysis for:

- Job requirement extraction
- Required-document analysis
- Company intelligence
- Credential/job matching assistance

The live deployment uses the configured Groq AI provider when
`AI_ENABLED=true`.

AI does **not** make the deterministic eligibility decision.

### 🔎 Deterministic Eligibility

Eligibility is calculated by the backend using trusted structured
credential metadata.

The system evaluates:

- Degree
- CGPA
- Graduation year

For example:

```text
Credential CGPA: 9.6
Job minimum CGPA: 5.0

→ CGPA requirement: PASS