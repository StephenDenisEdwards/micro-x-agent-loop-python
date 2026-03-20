"""LinkedIn client using MCP via stdio"""

import json
import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class LinkedInClient:
    """Connects to LinkedIn via MCP stdio"""
    
    def __init__(self, config: dict):
        self.config = config
    
    def search_contract_roles(self) -> List[Dict]:
        """
        Search LinkedIn for UK contract roles matching criteria.
        Uses MCP to call linkedin_jobs.
        
        Search parameters:
        - Location: Remote, London, UK
        - Experience level: Senior, Lead, Principal
        - Job type: Contract
        - Keywords: .NET, Azure, C#, Microservices, AI/ML
        """
        logger.info("Searching LinkedIn for contract roles...")
        
        search_results = []
        
        # Multiple search passes with different keywords
        keywords = [
            "Senior .NET Architect",
            "Senior Software Architect Azure",
            "Technical Lead .NET Core",
            "Principal Engineer C#",
            "Senior AI/ML Engineer",
        ]
        
        for keyword in keywords:
            logger.info(f"  Searching for: {keyword}")
            # MCP call would be: linkedin_jobs(
            #     keyword=keyword,
            #     location='Remote',
            #     experienceLevel='senior',
            #     jobType='contract',
            #     dateSincePosted='24hr'
            # )
            # For now, return empty list as placeholder
            pass
        
        return search_results
    
    def get_job_details(self, job_url: str) -> Optional[Dict]:
        """
        Get full job details from LinkedIn job URL.
        Uses MCP to call linkedin_job_detail.
        """
        logger.info(f"Fetching LinkedIn job details: {job_url}")
        
        # MCP call would be: linkedin_job_detail(url=job_url)
        # For now, return None as placeholder
        return None
    
    def _parse_linkedin_job(self, job_data: Dict) -> Dict:
        """
        Parse LinkedIn job data into standard format.
        
        Expected structure from linkedin_jobs / linkedin_job_detail:
        {
            'title': str,
            'company': str,
            'location': str,
            'salary': str (optional),
            'jobType': str,
            'url': str,
            'description': str,
            'postedDate': str,
            'workplaceType': str (on-site, remote, hybrid),
            'seniority': str,
        }
        """
        job = {
            'source': 'linkedin',
            'title': job_data.get('title', ''),
            'company': job_data.get('company', ''),
            'location': job_data.get('location', ''),
            'salary': job_data.get('salary'),
            'job_type': job_data.get('jobType', 'Permanent'),
            'workplace_type': job_data.get('workplaceType', 'Not specified'),
            'url': job_data.get('url', ''),
            'posted': job_data.get('postedDate', ''),
            'full_spec': job_data.get('description', ''),
        }
        
        # Extract technologies from description
        job['technologies'] = self._extract_technologies(job_data.get('description', ''))
        
        return job
    
    def _extract_technologies(self, description: str) -> List[str]:
        """Extract mentioned technologies from job description"""
        tech_keywords = [
            '.net', 'c#', 'azure', 'python', 'javascript', 'typescript',
            'react', 'angular', 'blazor', 'aspnet',
            'microservices', 'kubernetes', 'docker', 'containers',
            'ai', 'ml', 'machine learning', 'langchain', 'openai',
            'sql server', 'cosmos db', 'mongodb',
            'aws', 'gcp', 'cloud',
            'kafka', 'rabbitmq', 'service bus',
            'devops', 'ci/cd', 'azure devops', 'github',
        ]
        
        description_lower = description.lower()
        found_tech = []
        
        for tech in tech_keywords:
            if tech in description_lower and tech not in found_tech:
                found_tech.append(tech)
        
        return found_tech
