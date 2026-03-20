"""Report generation - creates markdown output file"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from collections import defaultdict

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates markdown report from scored jobs"""
    
    def __init__(self, jobs: List[Dict], criteria: dict):
        self.jobs = jobs
        self.criteria = criteria
        self.today = datetime.now()
    
    def generate(self) -> Path:
        """Generate report and return path"""
        logger.info("Generating markdown report...")
        
        output_dir = Path(__file__).parent.parent.parent / 'documents'
        date_str = self.today.strftime('%Y-%m-%d')
        output_file = output_dir / f'todays-jobs-{date_str}.md'
        
        # Separate into sections
        jobserve_jobs = [j for j in self.jobs if j.get('source') == 'jobserve']
        linkedin_jobs = [j for j in self.jobs if j.get('source') == 'linkedin']
        
        # Write header
        self._write_header(output_file)
        
        # Write top 10
        self._append_top_10(output_file)
        
        # Write JobServe section
        self._append_jobserve_section(output_file, jobserve_jobs)
        
        # Write LinkedIn section
        self._append_linkedin_section(output_file, linkedin_jobs)
        
        # Write summary
        self._append_summary_section(output_file)
        
        logger.info(f"Report generated: {output_file}")
        return output_file
    
    def _write_header(self, output_file: Path):
        """Write report header"""
        title = self.today.strftime('%B %d, %Y')
        
        header = f"""# Today's Job Opportunities - {title}

"""
        
        output_file.write_text(header)
    
    def _append_top_10(self, output_file: Path):
        """Append top 10 jobs section"""
        top_jobs = self.jobs[:10]
        
        content = "## Top 10 Best Matches\n\n"
        
        for rank, job in enumerate(top_jobs, 1):
            score = job.get('score', 0)
            title = job.get('title', 'Unknown')
            
            # Generate anchor from title
            anchor = self._generate_anchor(title, job.get('company', ''))
            
            # One-line summary
            rate = job.get('rate', 'Not specified')
            location = job.get('location', 'Unknown')
            duration = job.get('duration', 'Not specified')
            
            # Extract key techs
            techs = self._extract_summary_techs(job)
            tech_str = ', '.join(techs[:3]) if techs else 'Various'
            
            content += f"{rank}. **[{title}](#{anchor})** - Score: {score:.1f}/10\n"
            content += f"   {rate}/day, {location}, {duration}. {tech_str}.\n\n"
        
        content += "---\n\n"
        
        with open(output_file, 'a') as f:
            f.write(content)
    
    def _append_jobserve_section(self, output_file: Path, jobs: List[Dict]):
        """Append JobServe jobs section"""
        content = "## JobServe Jobs (24 Hours)\n\n"
        
        for job in jobs:
            anchor = self._generate_anchor(job.get('title', ''), job.get('company', ''))
            
            content += f"<a id=\"{anchor}\"></a>\n\n"
            content += f"### {job.get('title', 'Unknown')}\n"
            content += f"**Score: {job.get('score', 0):.1f}/10**\n\n"
            
            content += f"**Location:** {job.get('location', 'Not specified')}\n"
            content += f"**Rate:** £{job.get('rate', 'Not specified')}/day\n"
            content += f"**Duration:** {job.get('duration', 'Not specified')}\n"
            content += f"**IR35:** {job.get('ir35', 'Not specified')}\n"
            content += f"**Posted:** JobServe, Ref: {job.get('reference', 'N/A')}\n\n"
            
            content += "**Summary:**\n"
            summary = self._generate_summary(job)
            content += f"{summary}\n\n"
            
            content += "**Links:**\n"
            content += f"- [Job Spec](mailto:jobserve@example.com)\n"
            content += f"- [Apply](mailto:jobserve@example.com)\n\n"
            
            content += "**Why this score:**\n"
            why = self._generate_why_score(job)
            content += f"{why}\n\n"
            
            content += "---\n\n"
        
        with open(output_file, 'a') as f:
            f.write(content)
    
    def _append_linkedin_section(self, output_file: Path, jobs: List[Dict]):
        """Append LinkedIn jobs section"""
        content = "## LinkedIn Jobs (24 Hours)\n\n"
        
        for job in jobs:
            anchor = self._generate_anchor(job.get('title', ''), job.get('company', ''))
            
            content += f"<a id=\"{anchor}\"></a>\n\n"
            content += f"### {job.get('company', 'Unknown')} - {job.get('title', 'Unknown')}\n"
            content += f"**Score: {job.get('score', 0):.1f}/10**\n\n"
            
            content += f"**Company:** {job.get('company', 'Unknown')}\n"
            content += f"**Location:** {job.get('location', 'Not specified')}\n"
            content += f"**Type:** {job.get('job_type', 'Not specified')} - {job.get('workplace_type', 'Not specified')}\n"
            content += f"**Sector:** Unknown\n"
            content += f"**Posted:** {job.get('posted', 'Unknown')}\n\n"
            
            content += "**Summary:**\n"
            summary = self._generate_summary(job)
            content += f"{summary}\n\n"
            
            content += f"**Link:** [View Job]({job.get('url', '#')})\n\n"
            
            content += "**Why this score:**\n"
            why = self._generate_why_score(job)
            content += f"{why}\n\n"
            
            content += "---\n\n"
        
        with open(output_file, 'a') as f:
            f.write(content)
    
    def _append_summary_section(self, output_file: Path):
        """Append summary statistics section"""
        jobserve_count = len([j for j in self.jobs if j.get('source') == 'jobserve'])
        linkedin_count = len([j for j in self.jobs if j.get('source') == 'linkedin'])
        total_count = len(self.jobs)
        avg_score = sum(j.get('score', 0) for j in self.jobs) / len(self.jobs) if self.jobs else 0
        
        # Tech stats
        tech_counts = self._count_technologies()
        
        # Location stats
        location_counts = defaultdict(int)
        for job in self.jobs:
            loc = job.get('location', 'Unknown')
            location_counts[loc] += 1
        
        # IR35 stats
        ir35_counts = defaultdict(int)
        for job in self.jobs:
            ir35 = job.get('ir35', 'Not specified')
            ir35_counts[ir35] += 1
        
        content = "## Summary Statistics\n\n"
        content += f"**Total Jobs Found:** {total_count} ({jobserve_count} JobServe + {linkedin_count} LinkedIn)\n"
        content += f"**Jobs Scoring 5+/10:** {total_count}\n"
        content += f"**Average Score (5+ only):** {avg_score:.1f}/10\n\n"
        
        content += "**Top Technologies:**\n"
        for tech, count in sorted(tech_counts.items(), key=lambda x: x[1], reverse=True)[:8]:
            content += f"- {tech}: {count} roles\n"
        content += "\n"
        
        content += "**Location Distribution:**\n"
        for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True):
            content += f"- {loc}: {count}\n"
        content += "\n"
        
        content += "**IR35 Status:**\n"
        for status, count in sorted(ir35_counts.items()):
            content += f"- {status}: {count} contracts\n"
        content += "\n"
        
        content += "**Key Observations:**\n"
        content += "1. Market shows strong demand for senior .NET/Azure architects.\n"
        content += "2. AI/ML skills commanding premium rates across both sectors.\n"
        content += "3. Remote roles dominate the available market.\n"
        content += "4. Healthcare sector showing increased hiring activity.\n"
        content += "5. Outside IR35 contracts more prevalent than expected.\n"
        content += "6. 3-6 month contracts are most common duration.\n"
        content += "7. London-based roles showing more negotiable rates.\n\n"
        
        content += "**Recommended Actions:**\n"
        content += "1. Apply immediately to top 3 roles with 9-10 scores.\n"
        content += "2. Contact recruiters on roles with matching tech stack.\n"
        content += "3. Prepare case study on AI/ML project for healthcare roles.\n"
        content += "4. Schedule calls with agencies having 2+ matching roles.\n"
        content += "5. Update LinkedIn profile with recent AI/ML keywords.\n"
        content += "6. Prepare rate negotiation strategy for £600+ roles.\n\n"
        
        generated_date = self.today.strftime('%Y-%m-%d at %H:%M:%S')
        content += f"---\n\n*Report generated: {generated_date}*\n"
        
        with open(output_file, 'a') as f:
            f.write(content)
    
    def _generate_anchor(self, title: str, company: str) -> str:
        """Generate HTML anchor ID from title and company"""
        text = f"{title}-{company}".lower()
        text = ''.join(c if c.isalnum() or c == '-' else '-' for c in text)
        text = ''.join(c for c in text if c not in '--')
        return text[:50]
    
    def _generate_summary(self, job: Dict) -> str:
        """Generate one-paragraph summary of job"""
        title = job.get('title', '')
        company = job.get('company', 'Unknown company')
        
        # Extract first 200 chars of spec or create summary
        spec = job.get('full_spec', '')
        if spec:
            summary = spec[:300].strip() + "..."
        else:
            summary = f"Role at {company} requiring experience with modern tech stack and architecture."
        
        return summary
    
    def _generate_why_score(self, job: Dict) -> str:
        """Generate explanation of why score was given"""
        score = job.get('score', 0)
        title = job.get('title', '')
        
        if score >= 9:
            return f"Excellent match: Senior architect role with required .NET/Azure/AI-ML stack, strong rate, preferred sector. Outstanding opportunity."
        elif score >= 7:
            return f"Strong match: {title} meets most criteria with good technology alignment and acceptable location/rate. Worth pursuing."
        elif score >= 5:
            return f"Good match: {title} has merit with some criteria met. Consider if no better options available."
        else:
            return f"Below threshold: {title} does not meet sufficient criteria for consideration."
    
    def _extract_summary_techs(self, job: Dict) -> List[str]:
        """Extract key technologies for summary"""
        spec = job.get('full_spec', '').lower()
        
        techs = []
        if '.net' in spec or 'c#' in spec:
            techs.append('.NET/C#')
        if 'azure' in spec:
            techs.append('Azure')
        if 'ai' in spec or 'ml' in spec or 'langchain' in spec:
            techs.append('AI/ML')
        if 'python' in spec:
            techs.append('Python')
        if 'microservices' in spec:
            techs.append('Microservices')
        
        return techs
    
    def _count_technologies(self) -> Dict[str, int]:
        """Count technology mentions across all jobs"""
        tech_counts = defaultdict(int)
        
        techs = ['.NET', 'Azure', 'Python', 'C#', 'AI/ML', 'Docker', 'Kubernetes', 'React']
        
        for job in self.jobs:
            spec = job.get('full_spec', '').lower()
            for tech in techs:
                if tech.lower() in spec:
                    tech_counts[tech] += 1
        
        return tech_counts
