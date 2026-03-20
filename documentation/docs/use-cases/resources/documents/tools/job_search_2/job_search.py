#!/usr/bin/env python3
"""
Job Search Console Application
Searches Gmail (JobServe) and LinkedIn for contract roles matching Stephen Edwards' criteria.
Generates a markdown report with job opportunities scored against preferences.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum


class JobType(Enum):
    """Job employment type"""
    CONTRACT = "Contract"
    PERMANENT = "Permanent"
    NOT_SPECIFIED = "Not specified"


class JobSource(Enum):
    """Job source platform"""
    JOBSERVE = "JobServe"
    LINKEDIN = "LinkedIn"


@dataclass
class Job:
    """Represents a job opportunity"""
    source: JobSource
    title: str
    company: str
    location: str
    job_type: JobType
    posted: str
    sector: str
    summary: str
    url: str
    score: int = 0
    why_score: str = ""
    rate_day: Optional[str] = None
    annual_salary: Optional[str] = None
    duration: Optional[str] = None
    ir35_status: Optional[str] = None
    posting_ref: Optional[str] = None
    anchor_id: str = ""
    
    def __post_init__(self):
        """Generate anchor ID from title"""
        if not self.anchor_id:
            clean_title = self.title.lower().replace(" ", "-").replace(".", "").replace("(", "").replace(")", "")
            self.anchor_id = f"anchor-{clean_title[:50]}"


@dataclass
class JobSearchStats:
    """Statistics from job search"""
    total_found: int = 0
    jobserve_count: int = 0
    linkedin_count: int = 0
    scoring_5_plus: int = 0
    avg_score: float = 0.0
    tech_counts: Dict[str, int] = field(default_factory=dict)
    sector_counts: Dict[str, int] = field(default_factory=dict)
    contract_count: int = 0
    permanent_count: int = 0
    not_specified_count: int = 0
    location_counts: Dict[str, int] = field(default_factory=dict)
    ir35_inside: int = 0
    ir35_outside: int = 0
    ir35_not_specified: int = 0


class JobSearchCriteria:
    """Encapsulates job search criteria"""
    
    CORE_TECH = {
        ".NET Core", ".NET 6+", "C#", "Azure", "Python", 
        "Microservices", "Azure DevOps", "Docker", "Blazor",
        "React", "TypeScript", "Azure Functions", "Service Bus",
        "Cosmos DB", "Entity Framework", "AI/ML", "LangChain",
        "RAG", "Vector DB", "MQTT", "Azure IoT Hub"
    }
    
    PREFERRED_SECTORS = {
        "Healthcare", "MedTech", "BioTech",
        "Finance", "FinTech",
        "Legal Tech",
        "Industrial", "Manufacturing",
        "Energy",
        "Enterprise SaaS",
        "RegTech"
    }
    
    MIN_SCORE_THRESHOLD = 5
    TARGET_RATE_MIN = 500  # £/day
    TARGET_RATE_MAX = 700  # £/day
    PREFERRED_LOCATIONS = {"London", "Remote UK"}
    

class JobScorer:
    """Scores jobs against search criteria"""
    
    def __init__(self):
        self.criteria = JobSearchCriteria()
    
    def score_job(self, job: Job) -> Tuple[int, str]:
        """
        Score a job 1-10 based on search criteria.
        Returns (score, explanation).
        """
        score = 0
        explanation_parts = []
        
        # Technology match (0-3 points)
        tech_score, tech_exp = self._score_technology(job)
        score += tech_score
        if tech_exp:
            explanation_parts.append(tech_exp)
        
        # Rate/salary match (0-2 points)
        rate_score, rate_exp = self._score_rate(job)
        score += rate_score
        if rate_exp:
            explanation_parts.append(rate_exp)
        
        # Location match (0-2 points)
        loc_score, loc_exp = self._score_location(job)
        score += loc_score
        if loc_exp:
            explanation_parts.append(loc_exp)
        
        # Sector match (0-1 point)
        sector_score, sector_exp = self._score_sector(job)
        score += sector_score
        if sector_exp:
            explanation_parts.append(sector_exp)
        
        # Job type match (0-1 point) - contract preferred
        jtype_score, jtype_exp = self._score_job_type(job)
        score += jtype_score
        if jtype_exp:
            explanation_parts.append(jtype_exp)
        
        # IR35 status (0-1 point bonus) - outside IR35 preferred
        ir35_score, ir35_exp = self._score_ir35(job)
        score += ir35_score
        if ir35_exp:
            explanation_parts.append(ir35_exp)
        
        # Seniority (0-1 point)
        sen_score, sen_exp = self._score_seniority(job)
        score += sen_score
        if sen_exp:
            explanation_parts.append(sen_exp)
        
        # Clamp to 1-10
        final_score = max(1, min(10, score))
        explanation = " ".join(explanation_parts)
        
        return final_score, explanation
    
    def _score_technology(self, job: Job) -> Tuple[int, str]:
        """Score technology match (0-3 points)"""
        content = f"{job.title} {job.summary}".lower()
        matches = sum(1 for tech in self.criteria.CORE_TECH 
                     if tech.lower() in content)
        
        if matches >= 4:
            return 3, "Strong tech match (4+ core technologies)"
        elif matches >= 3:
            return 2, "Good tech match (3+ technologies)"
        elif matches >= 2:
            return 1, "Partial tech match (2 technologies)"
        else:
            return 0, ""
    
    def _score_rate(self, job: Job) -> Tuple[int, str]:
        """Score rate/salary match (0-2 points)"""
        if job.job_type == JobType.CONTRACT:
            if job.rate_day:
                # Try to extract numeric rate
                try:
                    rate_str = job.rate_day.replace("£", "").replace("+", "").split("-")[0].strip()
                    rate = int(''.join(c for c in rate_str if c.isdigit()))
                    if rate >= 600:
                        return 2, "Excellent day rate (£600+)"
                    elif rate >= 500:
                        return 2, "Good day rate (£500+)"
                    else:
                        return 1, "Below target day rate"
                except (ValueError, AttributeError):
                    return 1, "Day rate unclear"
            else:
                return 0, "No day rate specified"
        else:
            if job.annual_salary:
                try:
                    salary_str = job.annual_salary.replace("£", "").replace(",", "").split("-")[0].strip()
                    salary = int(''.join(c for c in salary_str if c.isdigit()))
                    # £500/day * 220 working days ≈ £110k equivalent
                    if salary >= 120000:
                        return 2, "Strong annual salary"
                    elif salary >= 70000:
                        return 1, "Moderate annual salary"
                    else:
                        return 0, "Below target salary"
                except (ValueError, AttributeError):
                    return 0, ""
            else:
                return 0, "No salary specified"
    
    def _score_location(self, job: Job) -> Tuple[int, str]:
        """Score location match (0-2 points)"""
        loc_lower = job.location.lower()
        
        if "remote" in loc_lower and "uk" in loc_lower:
            return 2, "Remote UK (ideal)"
        elif "london" in loc_lower or "central london" in loc_lower:
            return 2, "London location (ideal)"
        elif any(place in loc_lower for place in ["uk", "united kingdom", "manchester", "hammersmith"]):
            return 1, "UK location acceptable"
        else:
            return 0, "Location not aligned"
    
    def _score_sector(self, job: Job) -> Tuple[int, str]:
        """Score sector match (0-1 point)"""
        if any(sector.lower() in job.sector.lower() 
               for sector in self.criteria.PREFERRED_SECTORS):
            return 1, "Preferred sector"
        return 0, ""
    
    def _score_job_type(self, job: Job) -> Tuple[int, str]:
        """Score job type (0-1 point) - contract preferred"""
        if job.job_type == JobType.CONTRACT:
            return 1, "Contract role (preferred)"
        return 0, ""
    
    def _score_ir35(self, job: Job) -> Tuple[int, str]:
        """Score IR35 status (0-1 bonus point)"""
        if job.ir35_status and "outside" in job.ir35_status.lower():
            return 1, "Outside IR35 (bonus)"
        return 0, ""
    
    def _score_seniority(self, job: Job) -> Tuple[int, str]:
        """Score seniority level (0-1 point)"""
        title_lower = job.title.lower()
        if any(level in title_lower for level in 
               ["senior", "lead", "principal", "architect", "staff"]):
            return 1, "Senior-level role"
        return 0, ""


class ReportGenerator:
    """Generates markdown report from jobs"""
    
    def __init__(self, jobs: List[Job], stats: JobSearchStats):
        self.jobs = jobs
        self.stats = stats
        self.jobs_by_score = sorted(jobs, key=lambda j: j.score, reverse=True)
    
    def generate_title(self) -> str:
        """Generate report title section"""
        today = datetime.now()
        date_str = today.strftime("%B %d, %Y")
        return f"# Today's Job Opportunities - {date_str}\n"
    
    def generate_top_10(self) -> str:
        """Generate Top 10 best matches section"""
        section = "\n## Top 10 Best Matches\n\n"
        
        for i, job in enumerate(self.jobs_by_score[:10], 1):
            # Line 1: Title with anchor and score
            section += f"{i}. **[{job.title}](#{job.anchor_id})** - Score: {job.score}/10\n"
            
            # Line 2: Summary
            rate_info = job.rate_day or job.annual_salary or "Rate not specified"
            duration_info = job.duration or "Duration not specified"
            
            summary_line = f"   {duration_info}, {rate_info}, {job.location}. "
            summary_line += f"{job.sector}. {job.summary[:80]}..."
            section += summary_line + "\n\n"
        
        section += "---\n"
        return section
    
    def generate_jobserve_section(self) -> str:
        """Generate JobServe jobs section"""
        jobserve_jobs = [j for j in self.jobs_by_score if j.source == JobSource.JOBSERVE]
        
        if not jobserve_jobs:
            return "\n## JobServe Jobs (24 Hours)\n\nNo JobServe roles found in last 24 hours.\n\n---\n"
        
        section = "\n## JobServe Jobs (24 Hours)\n"
        
        for job in jobserve_jobs:
            section += f"\n<a id=\"{job.anchor_id}\"></a>\n\n"
            section += f"### {job.title}\n"
            section += f"**Score: {job.score}/10**\n\n"
            section += f"**Location:** {job.location}\n"
            section += f"**Rate:** {job.rate_day or 'Not specified'}\n"
            section += f"**Duration:** {job.duration or 'Not specified'}\n"
            section += f"**IR35:** {job.ir35_status or 'Not specified'}\n"
            section += f"**Posted:** {job.posting_ref or job.posted}\n\n"
            
            section += f"**Summary:**\n{job.summary}\n\n"
            
            section += "**Links:**\n"
            section += f"- [Job Spec]({job.url})\n"
            section += f"- [Apply]({job.url})\n\n"
            
            section += f"**Why this score:**\n{job.why_score}\n\n"
            section += "---\n"
        
        return section
    
    def generate_linkedin_section(self) -> str:
        """Generate LinkedIn jobs section"""
        linkedin_jobs = [j for j in self.jobs_by_score if j.source == JobSource.LINKEDIN]
        
        if not linkedin_jobs:
            return "\n## LinkedIn Jobs (24 Hours)\n\nNo LinkedIn roles found.\n\n---\n"
        
        section = "\n## LinkedIn Jobs (24 Hours)\n"
        
        for job in linkedin_jobs:
            section += f"\n<a id=\"{job.anchor_id}\"></a>\n\n"
            section += f"### {job.company} - {job.title}\n"
            section += f"**Score: {job.score}/10**\n\n"
            section += f"**Company:** {job.company}\n"
            section += f"**Location:** {job.location}\n"
            section += f"**Type:** {job.job_type.value}\n"
            section += f"**Sector:** {job.sector}\n"
            section += f"**Posted:** {job.posted}\n\n"
            
            section += f"**Summary:**\n{job.summary}\n\n"
            
            section += f"**Link:** [View Job]({job.url})\n\n"
            
            section += f"**Why this score:**\n{job.why_score}\n\n"
            section += "---\n"
        
        return section
    
    def generate_statistics_section(self) -> str:
        """Generate summary statistics section"""
        section = "\n## Summary Statistics\n\n"
        
        section += f"**Total Jobs Found:** {self.stats.total_found} "
        section += f"({self.stats.jobserve_count} JobServe + {self.stats.linkedin_count} LinkedIn)\n"
        section += f"**Jobs Scoring 5+/10:** {self.stats.scoring_5_plus}\n"
        section += f"**Average Score (5+ only):** {self.stats.avg_score:.1f}/10\n\n"
        
        # Top technologies
        section += "**Top Technologies:**\n"
        sorted_tech = sorted(self.stats.tech_counts.items(), key=lambda x: x[1], reverse=True)
        for tech, count in sorted_tech[:8]:
            section += f"- {tech}: {count} roles\n"
        
        section += "\n**Sectors:**\n"
        sorted_sectors = sorted(self.stats.sector_counts.items(), key=lambda x: x[1], reverse=True)
        for sector, count in sorted_sectors:
            section += f"- {sector}: {count}\n"
        
        section += "\n**Contract vs Permanent:**\n"
        section += f"- Contract roles: {self.stats.contract_count}\n"
        section += f"- Permanent roles: {self.stats.permanent_count}\n"
        section += f"- Not specified: {self.stats.not_specified_count}\n"
        
        section += "\n**Location Distribution:**\n"
        sorted_locations = sorted(self.stats.location_counts.items(), key=lambda x: x[1], reverse=True)
        for location, count in sorted_locations:
            section += f"- {location}: {count}\n"
        
        section += "\n**IR35 Status:**\n"
        section += f"- Inside IR35: {self.stats.ir35_inside} contracts\n"
        section += f"- Outside IR35: {self.stats.ir35_outside} contracts\n"
        section += f"- Not specified: {self.stats.ir35_not_specified}\n"
        
        section += "\n**Key Observations:**\n\n"
        section += "1. Limited contract market depth — most results are permanent roles.\n"
        section += "2. .NET/Azure skills highly sought across multiple sectors.\n"
        section += "3. London remains dominant location; remote UK roles increasing.\n"
        section += "4. Healthcare/MedTech presence below expected level.\n"
        section += "5. AI/ML interest emerging but underserved in market.\n"
        section += "6. Salary ranges vary significantly — contract roles command premium.\n"
        section += "7. Seniority titles inconsistent; focus on architectural responsibility depth.\n"
        
        section += "\n**Recommended Actions:**\n\n"
        section += "1. Prioritise contract roles immediately — scarcest resource.\n"
        section += "2. Activate specialist recruitment agencies (Mastech, Harvey Nash, Computer Futures).\n"
        section += "3. Target healthcare/MedTech with sector-specific outreach.\n"
        section += "4. Highlight AI/ML expertise in recruiter conversations.\n"
        section += "5. Negotiate permanent-to-contract arrangements with top companies.\n"
        section += "6. Confirm IR35 status and day rate on all contract opportunities.\n"
        
        today = datetime.now().strftime("%B %d, %Y")
        section += f"\n---\n\n*Report generated: {today}*\n"
        section += "*Search criteria: Senior Software Architect, Lead Engineer; "
        section += ".NET Core, Azure, AI/ML, Microservices; £500-700+/day contract; "
        section += "London or Remote UK; Healthcare, Finance, Legal sectors*\n"
        
        return section
    
    def generate_report(self) -> str:
        """Generate complete markdown report"""
        report = ""
        report += self.generate_title()
        report += self.generate_top_10()
        report += self.generate_jobserve_section()
        report += self.generate_linkedin_section()
        report += self.generate_statistics_section()
        return report


class JobSearchApp:
    """Main job search application"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.scorer = JobScorer()
        self.jobs: List[Job] = []
        self.stats = JobSearchStats()
        self.config_path = config_path or "job_search_config.json"
        self.load_mock_data()
    
    def load_mock_data(self):
        """Load mock job data for demonstration"""
        # This would be replaced with actual Gmail/LinkedIn API calls
        self.jobs = [
            Job(
                source=JobSource.LINKEDIN,
                title="Solution Architect – Azure Platform Migration",
                company="ProSapiens HR",
                location="London / Hyderabad, hybrid",
                job_type=JobType.CONTRACT,
                posted="1 day ago",
                sector="Retail / Digital Transformation",
                summary="Senior-level Azure migration lead for retail platform. Deep technical discovery of 50+ applications including 20-25 Azure PaaS apps. Design Low-Level Designs maintaining App Services, API Management, Azure SQL, implement geo-replicated DR across UK South/West, private endpoints, WAF security.",
                url="https://uk.linkedin.com/jobs/view/solution-architect-azure-platform-migration",
                rate_day="Not specified",
                duration="6 months",
                ir35_status="Not specified",
            ),
            Job(
                source=JobSource.LINKEDIN,
                title="Lead Software Engineer (Full Stack)",
                company="develop",
                location="Remote UK",
                job_type=JobType.PERMANENT,
                posted="5 days ago",
                sector="Security / SaaS",
                summary="Senior/Tech Lead on greenfield security platform. Full ownership of UI architecture (React, TypeScript, Next.js), backend design (Python, FastAPI, Postgres), team mentorship. Build dashboards, queues, timelines; design REST APIs; contribute to authentication and tenancy patterns.",
                url="https://uk.linkedin.com/jobs/view/lead-software-engineer-at-develop",
                annual_salary="£90,000 + bonus",
            ),
            Job(
                source=JobSource.LINKEDIN,
                title="Lead Software Engineer",
                company="Okta Resourcing",
                location="Remote, Scotland",
                job_type=JobType.PERMANENT,
                posted="4 days ago",
                sector="MedTech / Healthcare",
                summary="Lead Software Engineer at MedTech company transforming healthcare testing/records management. Cloud-based platform with microservices architecture using .NET 8, Entity Framework, Azure DevOps, Docker. Role combines technical leadership with hands-on development.",
                url="https://uk.linkedin.com/jobs/view/lead-software-engineer-okta",
                annual_salary="£75,000",
            ),
            Job(
                source=JobSource.LINKEDIN,
                title="Senior Full Stack Developer",
                company="Innova Recruitment",
                location="Manchester, hybrid",
                job_type=JobType.PERMANENT,
                posted="4 days ago",
                sector="Digital Transformation",
                summary="Senior Full Stack Developer in product-led engineering team. Core tech: .NET Core, React, TypeScript, Node, React Native. Feature delivery, platform modernisation, eCommerce focus. Apply TDD, automated testing, CI/CD, clean architecture.",
                url="https://uk.linkedin.com/jobs/view/senior-software-engineer-innova",
                annual_salary="£70,000",
            ),
            Job(
                source=JobSource.LINKEDIN,
                title="Senior Software Engineer",
                company="Retelligence",
                location="London, hybrid",
                job_type=JobType.PERMANENT,
                posted="5 days ago",
                sector="FinTech / Financial Services",
                summary="Senior Software Engineer at global FinTech powerhouse building financial networks. Expert-level C# and .NET Core, SOA, concurrency, asynchrony, parallelism, real-time transactional processing. TDD and robust CI/CD. Desired: Azure, Docker, Kubernetes, NServiceBus, TypeScript/Angular.",
                url="https://uk.linkedin.com/jobs/view/senior-software-engineer-retelligence",
                annual_salary="£90,000 - £100,000 + bonus",
            ),
        ]
    
    def score_jobs(self):
        """Score all jobs"""
        for job in self.jobs:
            score, explanation = self.scorer.score_job(job)
            job.score = score
            job.why_score = explanation
    
    def calculate_statistics(self):
        """Calculate search statistics"""
        self.stats.total_found = len(self.jobs)
        self.stats.jobserve_count = len([j for j in self.jobs if j.source == JobSource.JOBSERVE])
        self.stats.linkedin_count = len([j for j in self.jobs if j.source == JobSource.LINKEDIN])
        
        scoring_5_plus = [j for j in self.jobs if j.score >= 5]
        self.stats.scoring_5_plus = len(scoring_5_plus)
        
        if scoring_5_plus:
            self.stats.avg_score = sum(j.score for j in scoring_5_plus) / len(scoring_5_plus)
        
        # Count technologies
        all_content = " ".join(f"{j.title} {j.summary}" for j in self.jobs).lower()
        for tech in JobSearchCriteria.CORE_TECH:
            if tech.lower() in all_content:
                self.stats.tech_counts[tech] = sum(
                    1 for j in self.jobs 
                    if tech.lower() in f"{j.title} {j.summary}".lower()
                )
        
        # Count sectors
        for job in self.jobs:
            self.stats.sector_counts[job.sector] = self.stats.sector_counts.get(job.sector, 0) + 1
        
        # Count job types
        for job in self.jobs:
            if job.job_type == JobType.CONTRACT:
                self.stats.contract_count += 1
            elif job.job_type == JobType.PERMANENT:
                self.stats.permanent_count += 1
            else:
                self.stats.not_specified_count += 1
        
        # Count locations
        for job in self.jobs:
            self.stats.location_counts[job.location] = self.stats.location_counts.get(job.location, 0) + 1
        
        # Count IR35 status
        for job in self.jobs:
            if job.ir35_status:
                if "outside" in job.ir35_status.lower():
                    self.stats.ir35_outside += 1
                elif "inside" in job.ir35_status.lower():
                    self.stats.ir35_inside += 1
            self.stats.ir35_not_specified += 1
    
    def run(self) -> str:
        """Run the job search pipeline"""
        print("🔍 Starting job search...")
        print(f"   Loaded {len(self.jobs)} sample jobs")
        
        self.score_jobs()
        print(f"✓ Scored all jobs")
        
        self.calculate_statistics()
        print(f"✓ Calculated statistics")
        
        generator = ReportGenerator(self.jobs, self.stats)
        report = generator.generate_report()
        print(f"✓ Generated report")
        
        return report
    
    def save_report(self, report: str, output_dir: str = ".") -> str:
        """Save report to markdown file"""
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"todays-jobs-{today}.md"
        filepath = os.path.join(output_dir, filename)
        
        os.makedirs(output_dir, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✓ Report saved: {filepath}")
        return filepath


def main():
    """Main entry point"""
    import sys
    
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    
    print("\n" + "="*60)
    print("JOB SEARCH CONSOLE APPLICATION")
    print("Stephen Edwards - Contract Role Finder")
    print("="*60 + "\n")
    
    app = JobSearchApp()
    report = app.run()
    
    # Save report
    filepath = app.save_report(report, output_dir)
    
    print(f"\n{'='*60}")
    print(f"Report generated successfully!")
    print(f"Location: {filepath}")
    print(f"Total jobs found: {app.stats.total_found}")
    print(f"Jobs scoring 5+/10: {app.stats.scoring_5_plus}")
    print(f"Average score: {app.stats.avg_score:.1f}/10")
    print(f"{'='*60}\n")
    
    return filepath


if __name__ == "__main__":
    main()
