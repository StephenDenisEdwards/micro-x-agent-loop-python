"""
LinkedIn client using MCP (Message Passing Protocol) for actual implementation.

This replaces linkedin_client.py when MCP servers are available.
"""

import re
import logging
from typing import List, Dict, Optional

from mcp_client import LinkedInMCPClient, create_linkedin_client

logger = logging.getLogger(__name__)


class LinkedInClientMCP:
    """LinkedIn client using MCP protocol for stdio-based communication"""
    
    def __init__(self, config: dict, mcp_client: Optional[LinkedInMCPClient] = None):
        self.config = config
        self.mcp = mcp_client or create_linkedin_client()
        self.is_connected = False
    
    def connect(self) -> bool:
        """Establish connection to LinkedIn MCP server"""
        self.is_connected = self.mcp.connect()
        if self.is_connected:
            logger.info("Connected to LinkedIn MCP server")
        else:
            logger.error("Failed to connect to LinkedIn MCP server")
        return self.is_connected
    
    def disconnect(self):
        """Close LinkedIn MCP connection"""
        self.mcp.disconnect()
        self.is_connected = False
    
    def search_contract_roles(self) -> List[Dict]:
        """
        Search LinkedIn for UK contract roles matching criteria via MCP.
        
        Search parameters:
        - Location: Remote UK, London
        - Experience level: Senior, Lead, Principal
        - Job type: Contract
        - Keywords: .NET, Azure, C#, Microservices, AI/ML, Python
        - Date: Last 24 hours
        
        Returns:
            List of job dicts with title, company, location, url, salary, etc.
        """
        if not self.is_connected:
            logger.warning("Not connected to LinkedIn MCP server")
            return []
        
        all_jobs = []
        
        # Search with different keyword combinations
        search_params = [
            {
                'keyword': 'Senior .NET Architect',
                'location': 'Remote UK',
                'job_type': 'contract',
                'experience_level': 'senior',
            },
            {
                'keyword': 'Senior Software Architect Azure',
                'location': 'London',
                'job_type': 'contract',
                'experience_level': 'senior',
            },
            {
                'keyword': 'Technical Lead C#',
                'location': 'Remote UK',
                'job_type': 'contract',
                'experience_level': 'senior',
            },
            {
                'keyword': 'Principal Engineer Microservices',
                'location': 'London',
                'job_type': 'contract',
            },
            {
                'keyword': 'Senior AI Engineer Python',
                'location': 'Remote UK',
                'job_type': 'contract',
                'experience_level': 'senior',
            },
            {
                'keyword': 'Solution Architect Azure',
                'location': 'London',
                'job_type': 'contract',
            },
        ]
        
        for params in search_params:
            logger.info(f"Searching LinkedIn: {params.get('keyword', '')} in {params.get('location', 'any')}")
            
            results = self.mcp.search_jobs(
                keyword=params.get('keyword'),
                location=params.get('location'),
                job_type=params.get('job_type'),
                experience_level=params.get('experience_level'),
                date_since_posted='24hr',
                limit=10,
            )
            
            if results:
                # Get full details for each job
                for result in results:
                    if 'url' in result:
                        full_job = self.mcp.get_job_details(result['url'])
                        if full_job:
                            job = self._parse_linkedin_job(full_job)
                            all_jobs.append(job)
                    else:
                        job = self._parse_linkedin_job(result)
                        all_jobs.append(job)
        
        # Remove duplicates by URL
        seen_urls = set()
        unique_jobs = []
        for job in all_jobs:
            url = job.get('url', '')
            if url not in seen_urls:
                seen_urls.add(url)
                unique_jobs.append(job)
        
        logger.info(f"Found {len(unique_jobs)} unique LinkedIn jobs")
        return unique_jobs
    
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
            'postedDate': str or 'Posted X days ago',
            'workplaceType': str,
            'seniority': str,
        }
        """
        try:
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
                'seniority': job_data.get('seniority', ''),
            }
            
            # Extract technologies from description
            job['technologies'] = self._extract_technologies(job_data.get('description', ''))
            
            # Detect sector from description
            job['sector'] = self._detect_sector(job_data.get('description', ''))
            
            logger.debug(f"Parsed LinkedIn job: {job.get('title', 'Unknown')} - Score pending")
            return job
        
        except Exception as e:
            logger.error(f"Error parsing LinkedIn job: {e}")
            return {}
    
    def _extract_technologies(self, description: str) -> List[str]:
        """Extract mentioned technologies from job description"""
        tech_keywords = {
            '.net': ['.net', 'dotnet', '.net core', '.net 6', '.net 7', '.net 8', '.net 9'],
            'c#': ['c#', 'csharp'],
            'azure': ['azure', 'microsoft azure'],
            'python': ['python'],
            'javascript': ['javascript', 'js', 'node.js', 'typescript'],
            'react': ['react', 'react.js'],
            'angular': ['angular'],
            'blazor': ['blazor'],
            'aspnet': ['asp.net', 'aspnet'],
            'microservices': ['microservices', 'microservice'],
            'kubernetes': ['kubernetes', 'k8s'],
            'docker': ['docker', 'containers', 'container'],
            'ai': ['ai', 'artificial intelligence', 'machine learning', 'ml'],
            'langchain': ['langchain'],
            'openai': ['openai', 'gpt'],
            'sql server': ['sql server', 'mssql'],
            'cosmos db': ['cosmos db', 'cosmosdb'],
            'mongodb': ['mongodb', 'mongo'],
            'kafka': ['kafka'],
            'rabbitmq': ['rabbitmq', 'amqp'],
            'service bus': ['service bus', 'servicebus'],
            'devops': ['devops', 'ci/cd', 'cicd'],
            'azure devops': ['azure devops'],
            'github': ['github'],
        }
        
        description_lower = description.lower()
        found_tech = []
        
        for tech, keywords in tech_keywords.items():
            for keyword in keywords:
                if keyword in description_lower:
                    if tech not in found_tech:
                        found_tech.append(tech)
                    break
        
        return found_tech
    
    def _detect_sector(self, description: str) -> str:
        """Detect industry sector from job description"""
        description_lower = description.lower()
        
        sectors = {
            'Healthcare': ['healthcare', 'medical', 'pharma', 'health', 'hospital', 'clinic', 'fhir', 'hl7'],
            'Finance': ['finance', 'fintech', 'banking', 'financial', 'investment', 'trading'],
            'Legal': ['legal', 'law firm', 'attorney', 'litigation'],
            'Industrial': ['industrial', 'manufacturing', 'factory', 'plant'],
            'Energy': ['energy', 'utilities', 'oil', 'gas', 'power'],
            'Technology': ['technology', 'software', 'tech'],
            'Retail': ['retail', 'ecommerce', 'e-commerce'],
            'Media': ['media', 'entertainment', 'publishing'],
        }
        
        for sector, keywords in sectors.items():
            for keyword in keywords:
                if keyword in description_lower:
                    return sector
        
        return 'Unknown'
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
