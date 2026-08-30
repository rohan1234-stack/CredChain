"""
DEVELOPMENT-ONLY seed script for the student-facing Institution/Company
discovery directory (Phase 1 job-discovery work). Not imported or run by the
FastAPI app itself — run it manually.

Populates Institution and Company rows with a curated, real, India-first
dataset (real names, real public locations, real official websites) plus a
handful of real-shaped OPEN Job postings so the discovery → eligibility →
apply flow has something genuine to browse end to end.

These rows are DIRECTORY LISTINGS, not CredChain accounts: user_id is left
NULL (see the migration that made institutions.user_id/companies.user_id
nullable), so nothing here can log in, issue credentials, or post jobs
itself — being listed means "discoverable," never "a CredChain partner."
A real institution/company can still register normally later; that flow is
completely unaffected by this script.

Descriptions are intentionally generated from the structured fields
themselves (type/industry + location) rather than hand-written per-entry
narrative claims — at this dataset size, a templated, factual one-liner is
safer than 100+ unique claims that would be impractical to individually
verify.

Idempotent / safe to rerun:
  - each institution/company is looked up by name (case-insensitive) first
    and skipped if it already exists — never duplicated, never overwritten
  - each job is looked up by (company, title) and skipped if it already exists
  - never deletes anything, never touches users/students/credentials

Usage:
    cd backend
    venv\\Scripts\\Activate.ps1
    python -m scripts.seed_directory
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.enums import JobEmploymentType, JobStatus  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.models.job import Job  # noqa: E402

# (name, location "City, State/Region, Country", website, institution_type)
INSTITUTIONS: list[tuple[str, str, str, str]] = [
    ("Indian Institute of Technology Bombay", "Mumbai, Maharashtra, India", "https://www.iitb.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Delhi", "New Delhi, Delhi, India", "https://home.iitd.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Madras", "Chennai, Tamil Nadu, India", "https://www.iitm.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Kanpur", "Kanpur, Uttar Pradesh, India", "https://www.iitk.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Kharagpur", "Kharagpur, West Bengal, India", "https://www.iitkgp.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Roorkee", "Roorkee, Uttarakhand, India", "https://www.iitr.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Guwahati", "Guwahati, Assam, India", "https://www.iitg.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Hyderabad", "Hyderabad, Telangana, India", "https://www.iith.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology (BHU) Varanasi", "Varanasi, Uttar Pradesh, India", "https://www.iitbhu.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Bhubaneswar", "Bhubaneswar, Odisha, India", "https://www.iitbbs.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Gandhinagar", "Gandhinagar, Gujarat, India", "https://iitgn.ac.in", "Public Technical Institute"),
    ("Indian Institute of Technology Indore", "Indore, Madhya Pradesh, India", "https://www.iiti.ac.in", "Public Technical Institute"),
    ("Indian Institute of Science", "Bengaluru, Karnataka, India", "https://www.iisc.ac.in", "Public Research Institute"),
    ("National Institute of Technology Tiruchirappalli", "Tiruchirappalli, Tamil Nadu, India", "https://www.nitt.edu", "Public Technical Institute"),
    ("National Institute of Technology Karnataka, Surathkal", "Mangaluru, Karnataka, India", "https://www.nitk.ac.in", "Public Technical Institute"),
    ("National Institute of Technology Rourkela", "Rourkela, Odisha, India", "https://www.nitrkl.ac.in", "Public Technical Institute"),
    ("National Institute of Technology Warangal", "Warangal, Telangana, India", "https://www.nitw.ac.in", "Public Technical Institute"),
    ("Malaviya National Institute of Technology Jaipur", "Jaipur, Rajasthan, India", "https://www.mnit.ac.in", "Public Technical Institute"),
    ("National Institute of Technology Calicut", "Kozhikode, Kerala, India", "https://www.nitc.ac.in", "Public Technical Institute"),
    ("Birla Institute of Technology and Science, Pilani", "Pilani, Rajasthan, India", "https://www.bits-pilani.ac.in", "Private Deemed University"),
    ("Delhi Technological University", "New Delhi, Delhi, India", "http://dtu.ac.in", "Public State University"),
    ("Netaji Subhas University of Technology", "New Delhi, Delhi, India", "https://www.nsut.ac.in", "Public State University"),
    ("Vellore Institute of Technology", "Vellore, Tamil Nadu, India", "https://vit.ac.in", "Private Deemed University"),
    ("SRM Institute of Science and Technology", "Kattankulathur, Tamil Nadu, India", "https://www.srmist.edu.in", "Private Deemed University"),
    ("Manipal Academy of Higher Education", "Manipal, Karnataka, India", "https://manipal.edu", "Private Deemed University"),
    ("Amrita Vishwa Vidyapeetham", "Coimbatore, Tamil Nadu, India", "https://www.amrita.edu", "Private Deemed University"),
    ("Anna University", "Chennai, Tamil Nadu, India", "https://www.annauniv.edu", "Public State University"),
    ("University of Delhi", "New Delhi, Delhi, India", "https://www.du.ac.in", "Public Central University"),
    ("Jawaharlal Nehru University", "New Delhi, Delhi, India", "https://www.jnu.ac.in", "Public Central University"),
    ("Jamia Millia Islamia", "New Delhi, Delhi, India", "https://jmi.ac.in", "Public Central University"),
    ("Banaras Hindu University", "Varanasi, Uttar Pradesh, India", "https://www.bhu.ac.in", "Public Central University"),
    ("Aligarh Muslim University", "Aligarh, Uttar Pradesh, India", "https://www.amu.ac.in", "Public Central University"),
    ("University of Mumbai", "Mumbai, Maharashtra, India", "https://mu.ac.in", "Public State University"),
    ("Savitribai Phule Pune University", "Pune, Maharashtra, India", "https://www.unipune.ac.in", "Public State University"),
    ("Jadavpur University", "Kolkata, West Bengal, India", "https://www.jaduniv.edu.in", "Public State University"),
    ("University of Calcutta", "Kolkata, West Bengal, India", "https://www.caluniv.ac.in", "Public State University"),
    ("Osmania University", "Hyderabad, Telangana, India", "https://www.osmania.ac.in", "Public State University"),
    ("International Institute of Information Technology, Hyderabad", "Hyderabad, Telangana, India", "https://www.iiit.ac.in", "Private Deemed University"),
    ("Indraprastha Institute of Information Technology Delhi", "New Delhi, Delhi, India", "https://www.iiitd.ac.in", "Public Technical Institute"),
    ("International Institute of Information Technology, Bangalore", "Bengaluru, Karnataka, India", "https://www.iiitb.ac.in", "Private Deemed University"),
    ("PSG College of Technology", "Coimbatore, Tamil Nadu, India", "https://www.psgtech.edu", "Private Autonomous College"),
    ("Thapar Institute of Engineering and Technology", "Patiala, Punjab, India", "https://www.thapar.edu", "Private Deemed University"),
    ("Chandigarh University", "Mohali, Punjab, India", "https://www.cuchd.in", "Private University"),
    ("Lovely Professional University", "Phagwara, Punjab, India", "https://www.lpu.in", "Private University"),
    ("CHRIST (Deemed to be University)", "Bengaluru, Karnataka, India", "https://christuniversity.in", "Private Deemed University"),
    ("Symbiosis International (Deemed University)", "Pune, Maharashtra, India", "https://www.siu.edu.in", "Private Deemed University"),
    ("Massachusetts Institute of Technology", "Cambridge, Massachusetts, United States", "https://www.mit.edu", "Private Research University"),
    ("Stanford University", "Stanford, California, United States", "https://www.stanford.edu", "Private Research University"),
    ("Harvard University", "Cambridge, Massachusetts, United States", "https://www.harvard.edu", "Private Research University"),
    ("University of Oxford", "Oxford, England, United Kingdom", "https://www.ox.ac.uk", "Public Research University"),
    ("University of Cambridge", "Cambridge, England, United Kingdom", "https://www.cam.ac.uk", "Public Research University"),
    ("National University of Singapore", "Singapore", "https://www.nus.edu.sg", "Public Research University"),
    ("Nanyang Technological University", "Singapore", "https://www.ntu.edu.sg", "Public Research University"),
    ("ETH Zurich", "Zurich, Switzerland", "https://ethz.ch", "Public Research University"),
    ("University of Toronto", "Toronto, Ontario, Canada", "https://www.utoronto.ca", "Public Research University"),
    ("University of Melbourne", "Melbourne, Victoria, Australia", "https://www.unimelb.edu.au", "Public Research University"),
]

# (name, industry, location, website)
COMPANIES: list[tuple[str, str, str, str]] = [
    ("Tata Consultancy Services", "IT Services & Consulting", "Mumbai, Maharashtra, India", "https://www.tcs.com"),
    ("Infosys", "IT Services & Consulting", "Bengaluru, Karnataka, India", "https://www.infosys.com"),
    ("Wipro", "IT Services & Consulting", "Bengaluru, Karnataka, India", "https://www.wipro.com"),
    ("HCLTech", "IT Services & Consulting", "Noida, Uttar Pradesh, India", "https://www.hcltech.com"),
    ("Tech Mahindra", "IT Services & Consulting", "Pune, Maharashtra, India", "https://www.techmahindra.com"),
    ("LTIMindtree", "IT Services & Consulting", "Mumbai, Maharashtra, India", "https://www.ltimindtree.com"),
    ("Mphasis", "IT Services & Consulting", "Bengaluru, Karnataka, India", "https://www.mphasis.com"),
    ("Persistent Systems", "IT Services & Consulting", "Pune, Maharashtra, India", "https://www.persistent.com"),
    ("Cyient", "Engineering Services", "Hyderabad, Telangana, India", "https://www.cyient.com"),
    ("Zensar Technologies", "IT Services & Consulting", "Pune, Maharashtra, India", "https://www.zensar.com"),
    ("Larsen & Toubro", "Engineering & Construction", "Mumbai, Maharashtra, India", "https://www.larsentoubro.com"),
    ("Reliance Industries", "Conglomerate", "Mumbai, Maharashtra, India", "https://www.ril.com"),
    ("Tata Motors", "Automotive", "Mumbai, Maharashtra, India", "https://www.tatamotors.com"),
    ("Mahindra & Mahindra", "Automotive", "Mumbai, Maharashtra, India", "https://www.mahindra.com"),
    ("Bajaj Auto", "Automotive", "Pune, Maharashtra, India", "https://www.bajajauto.com"),
    ("Zoho Corporation", "Software", "Chennai, Tamil Nadu, India", "https://www.zoho.com"),
    ("Freshworks", "Software", "Chennai, Tamil Nadu, India", "https://www.freshworks.com"),
    ("Flipkart", "E-commerce", "Bengaluru, Karnataka, India", "https://www.flipkart.com"),
    ("Swiggy", "Internet / Food Delivery", "Bengaluru, Karnataka, India", "https://www.swiggy.com"),
    ("Zomato", "Internet / Food Delivery", "Gurugram, Haryana, India", "https://www.zomato.com"),
    ("Paytm", "Fintech", "Noida, Uttar Pradesh, India", "https://paytm.com"),
    ("PhonePe", "Fintech", "Bengaluru, Karnataka, India", "https://www.phonepe.com"),
    ("Razorpay", "Fintech", "Bengaluru, Karnataka, India", "https://razorpay.com"),
    ("Ather Energy", "Electric Vehicles", "Bengaluru, Karnataka, India", "https://www.atherenergy.com"),
    ("Ola Electric", "Electric Vehicles", "Bengaluru, Karnataka, India", "https://www.olaelectric.com"),
    ("Nykaa", "E-commerce", "Mumbai, Maharashtra, India", "https://www.nykaa.com"),
    ("Myntra", "E-commerce / Fashion", "Bengaluru, Karnataka, India", "https://www.myntra.com"),
    ("MakeMyTrip", "Travel & Tourism", "Gurugram, Haryana, India", "https://www.makemytrip.com"),
    ("InMobi", "AdTech", "Bengaluru, Karnataka, India", "https://www.inmobi.com"),
    ("Bharti Airtel", "Telecommunications", "New Delhi, Delhi, India", "https://www.airtel.in"),
    ("Reliance Jio", "Telecommunications", "Mumbai, Maharashtra, India", "https://www.jio.com"),
    ("ICICI Bank", "Banking & Financial Services", "Mumbai, Maharashtra, India", "https://www.icicibank.com"),
    ("HDFC Bank", "Banking & Financial Services", "Mumbai, Maharashtra, India", "https://www.hdfcbank.com"),
    ("State Bank of India", "Banking & Financial Services", "Mumbai, Maharashtra, India", "https://www.sbi.co.in"),
    ("Axis Bank", "Banking & Financial Services", "Mumbai, Maharashtra, India", "https://www.axisbank.com"),
    ("Titan Company", "Consumer Goods", "Bengaluru, Karnataka, India", "https://www.titancompany.in"),
    ("Asian Paints", "Consumer Goods", "Mumbai, Maharashtra, India", "https://www.asianpaints.com"),
    ("Google", "Technology / Internet", "Mountain View, California, United States", "https://www.google.com"),
    ("Microsoft", "Technology / Software", "Redmond, Washington, United States", "https://www.microsoft.com"),
    ("Amazon", "Technology / E-commerce", "Seattle, Washington, United States", "https://www.amazon.com"),
    ("Meta", "Technology / Internet", "Menlo Park, California, United States", "https://about.meta.com"),
    ("Apple", "Technology / Consumer Electronics", "Cupertino, California, United States", "https://www.apple.com"),
    ("IBM", "Technology / IT Services", "Armonk, New York, United States", "https://www.ibm.com"),
    ("Oracle", "Enterprise Software", "Austin, Texas, United States", "https://www.oracle.com"),
    ("SAP", "Enterprise Software", "Walldorf, Germany", "https://www.sap.com"),
    ("Salesforce", "Enterprise Software", "San Francisco, California, United States", "https://www.salesforce.com"),
    ("Adobe", "Software", "San Jose, California, United States", "https://www.adobe.com"),
    ("Intel", "Semiconductors", "Santa Clara, California, United States", "https://www.intel.com"),
    ("NVIDIA", "Semiconductors", "Santa Clara, California, United States", "https://www.nvidia.com"),
    ("Qualcomm", "Semiconductors", "San Diego, California, United States", "https://www.qualcomm.com"),
    ("Accenture", "Consulting / IT Services", "Dublin, Ireland", "https://www.accenture.com"),
    ("Capgemini", "Consulting / IT Services", "Paris, France", "https://www.capgemini.com"),
    ("Deloitte", "Professional Services", "London, United Kingdom", "https://www.deloitte.com"),
    ("EY", "Professional Services", "London, United Kingdom", "https://www.ey.com"),
    ("KPMG", "Professional Services", "Amstelveen, Netherlands", "https://kpmg.com"),
    ("PwC", "Professional Services", "London, United Kingdom", "https://www.pwc.com"),
    ("Goldman Sachs", "Financial Services", "New York, New York, United States", "https://www.goldmansachs.com"),
    ("JPMorgan Chase", "Financial Services", "New York, New York, United States", "https://www.jpmorganchase.com"),
]

# (company_name, title, location, employment_type, required_degree, minimum_cgpa,
#  graduation_year_requirement, required_skills, required_documents, description)
JOBS: list[tuple] = [
    (
        "Tata Consultancy Services", "Assistant System Engineer", "Chennai, Tamil Nadu, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 6.0, 2026,
        ["Java", "SQL"], ["Resume", "Transcript", "Degree Certificate"],
        "Entry-level software engineering role working across TCS client delivery projects. Training provided on internal tools and client-specific stacks.",
    ),
    (
        "Infosys", "Systems Engineer Trainee", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech", 6.5, 2026,
        ["Python", "Problem Solving"], ["Resume", "Transcript", "Degree Certificate"],
        "Graduate trainee role starting with Infosys's foundation training program before assignment to a client engagement.",
    ),
    (
        "Wipro", "Project Engineer", "Hyderabad, Telangana, India",
        JobEmploymentType.FULL_TIME, "B.Tech", 6.0, 2026,
        ["Java", "Cloud Fundamentals"], ["Resume", "Transcript", "Degree Certificate"],
        "Entry-level engineering role on Wipro's cloud and infrastructure delivery teams.",
    ),
    (
        "HCLTech", "Graduate Engineer Trainee", "Noida, Uttar Pradesh, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 6.5, 2026,
        ["Data Structures", "SQL"], ["Resume", "Transcript", "Degree Certificate"],
        "Structured graduate program covering software engineering fundamentals and a rotation across HCLTech service lines.",
    ),
    (
        "Zoho Corporation", "Software Developer", "Chennai, Tamil Nadu, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 7.5, 2026,
        ["Java", "Data Structures", "Algorithms"], ["Resume", "Transcript", "Degree Certificate"],
        "Product engineering role building features across Zoho's suite of business applications.",
    ),
    (
        "Freshworks", "Associate Software Engineer", "Chennai, Tamil Nadu, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 7.0, 2026,
        ["JavaScript", "React", "Node.js"], ["Resume", "Transcript", "Degree Certificate"],
        "Full-stack engineering role on Freshworks's customer-engagement product line.",
    ),
    (
        "Flipkart", "SDE-1 (New Grad)", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 8.0, 2026,
        ["Java", "Data Structures", "System Design"], ["Resume", "Transcript", "Degree Certificate"],
        "New-graduate software engineering role on Flipkart's e-commerce platform teams.",
    ),
    (
        "Razorpay", "Backend Engineer - New Grad", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 8.0, 2026,
        ["Java", "Spring Boot", "SQL"], ["Resume", "Transcript", "Degree Certificate"],
        "Backend engineering role on Razorpay's payments infrastructure.",
    ),
    (
        "PhonePe", "Software Development Engineer I", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 7.5, 2026,
        ["Java", "Distributed Systems"], ["Resume", "Transcript", "Degree Certificate"],
        "SDE role on PhonePe's core payments and merchant platform teams.",
    ),
    (
        "Larsen & Toubro", "Graduate Engineer Trainee - Mechanical", "Mumbai, Maharashtra, India",
        JobEmploymentType.FULL_TIME, "B.Tech Mechanical Engineering", 6.0, 2026,
        ["AutoCAD", "Project Planning"], ["Resume", "Transcript", "Degree Certificate"],
        "Graduate engineer trainee program on L&T's engineering and construction project sites.",
    ),
    (
        "Tata Motors", "Graduate Engineer Trainee - Automotive", "Pune, Maharashtra, India",
        JobEmploymentType.FULL_TIME, "B.Tech Mechanical Engineering", 6.5, 2026,
        ["CAD", "Manufacturing Fundamentals"], ["Resume", "Transcript", "Degree Certificate"],
        "Graduate engineer trainee role across Tata Motors's vehicle engineering functions.",
    ),
    (
        "ICICI Bank", "Management Trainee - Technology", "Mumbai, Maharashtra, India",
        JobEmploymentType.FULL_TIME, "B.Tech", 6.5, 2026,
        ["SQL", "Analytical Thinking"], ["Resume", "Transcript", "Degree Certificate"],
        "Technology management trainee program within ICICI Bank's digital banking function.",
    ),
    (
        "Persistent Systems", "Software Engineer", "Pune, Maharashtra, India",
        JobEmploymentType.FULL_TIME, "B.Tech Computer Science", 7.0, 2026,
        ["Python", "Cloud Fundamentals"], ["Resume", "Transcript", "Degree Certificate"],
        "Software engineering role on Persistent's enterprise and cloud engagements.",
    ),
    (
        "Mphasis", "Associate Software Engineer", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech", 6.0, 2026,
        ["Java", "SQL"], ["Resume", "Transcript", "Degree Certificate"],
        "Entry-level engineering role on Mphasis's applications and cloud services teams.",
    ),
    (
        "Accenture", "Associate Software Engineer", "Bengaluru, Karnataka, India",
        JobEmploymentType.FULL_TIME, "B.Tech", 6.5, 2026,
        ["Java", "Problem Solving"], ["Resume", "Transcript", "Degree Certificate"],
        "Entry-level technology role within Accenture's India delivery centers.",
    ),
    (
        "Swiggy", "Data Analyst Intern", "Bengaluru, Karnataka, India",
        JobEmploymentType.INTERNSHIP, "B.Tech", 7.0, 2027,
        ["SQL", "Python", "Excel"], ["Resume", "Transcript"],
        "Internship on Swiggy's analytics team working with real operational and delivery data.",
    ),
]


def seed() -> None:
    db = SessionLocal()
    inst_created = inst_skipped = 0
    comp_created = comp_skipped = 0
    job_created = job_skipped = 0
    try:
        existing_institutions = {
            name.lower(): iid for iid, name in db.query(Institution.id, Institution.name).all()
        }
        for name, location, website, institution_type in INSTITUTIONS:
            if name.lower() in existing_institutions:
                inst_skipped += 1
                continue
            db.add(
                Institution(
                    user_id=None,
                    name=name,
                    location=location,
                    website=website,
                    institution_type=institution_type,
                    description=f"{name} is a {institution_type.lower()} located in {location}.",
                )
            )
            inst_created += 1
        db.commit()

        existing_companies = {name.lower(): cid for cid, name in db.query(Company.id, Company.name).all()}
        for name, industry, location, website in COMPANIES:
            if name.lower() in existing_companies:
                comp_skipped += 1
                continue
            db.add(
                Company(
                    user_id=None,
                    name=name,
                    industry=industry,
                    location=location,
                    website=website,
                    description=f"{name} is a company in the {industry} industry, headquartered in {location}.",
                )
            )
            comp_created += 1
        db.commit()

        # Re-fetch so newly-created companies above have real ids to attach jobs to.
        company_by_name = {c.name.lower(): c for c in db.query(Company).all()}
        for (
            company_name, title, location, employment_type, required_degree, minimum_cgpa,
            graduation_year_requirement, required_skills, required_documents, description,
        ) in JOBS:
            company = company_by_name.get(company_name.lower())
            if company is None:
                print(f"  WARNING: company '{company_name}' not found — skipping job '{title}'")
                continue
            already = (
                db.query(Job)
                .filter(Job.company_id == company.id, func.lower(Job.title) == title.lower())
                .first()
            )
            if already is not None:
                job_skipped += 1
                continue
            db.add(
                Job(
                    company_id=company.id,
                    title=title,
                    description=description,
                    location=location,
                    employment_type=employment_type,
                    required_degree=required_degree,
                    minimum_cgpa=minimum_cgpa,
                    graduation_year_requirement=graduation_year_requirement,
                    required_skills=required_skills,
                    required_certifications=[],
                    required_documents=required_documents,
                    status=JobStatus.OPEN,
                )
            )
            job_created += 1
        db.commit()

        print("Institution directory seed complete:")
        print(f"  institutions: {inst_created} created, {inst_skipped} already existed")
        print(f"  companies:    {comp_created} created, {comp_skipped} already existed")
        print(f"  jobs:         {job_created} created, {job_skipped} already existed")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
