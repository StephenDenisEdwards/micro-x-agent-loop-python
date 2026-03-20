"""Gmail client using MCP (Message Passing Protocol) via stdio"""

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class GmailClient:
    """Connects to Gmail via MCP stdio"""
    
    def __init__(self, config: dict):
        self.config = config
        self.mcp_process = None
    
    def _call_mcp(self, resource: str, params: dict) -> Optional[str]:
        """Call MCP via stdio - placeholder for actual implementation"""
        # This would connect to the MCP server via stdio
        # For now, returns None as placeholder
        logger.warning("MCP stdio connection not yet implemented")
        return None
    
    def search_jobserve_last_24h(self) -> List[Dict]:
        """
        Search Gmail for JobServe emails from last 24 hours.
        Uses MCP to call gmail_search.
        """
        logger.info("Searching Gmail for JobServe emails...")
        
        # Calculate date range
        now = datetime.utcnow()
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # MCP call to gmail_search
        # Query: from:jobserve after:yesterday
        query = f'from:jobserve after:{yesterday}'
        
        # This would be: mcp_result = self._call_mcp('gmail_search', {'query': query})
        # For now, return empty list as placeholder
        logger.info(f"Would search Gmail with query: {query}")
        return []
    
    def extract_jobs_from_emails(self, emails: List[Dict]) -> List[Dict]:
        """
        Extract job details from JobServe emails.
        Parses email content to extract:
        - Job title, company, location
        - Rate, duration, contract type
        - Description, tech stack, IR35 status
        """
        jobs = []
        
        for email in emails:
            job = self._parse_jobserve_email(email)
            if job:
                jobs.append(job)
        
        return jobs
    
    def _parse_jobserve_email(self, email: Dict) -> Optional[Dict]:
        """
        Parse a single JobServe email and extract job details.
        
        Expected email structure:
        {
            'id': message_id,
            'from': 'jobserve@...',
            'subject': 'Job Title - Company - Location',
            'body': full_email_content,
            'date': ISO date
        }
        """
        try:
            body = email.get('body', '')
            subject = email.get('subject', '')
            
            job = {
                'source': 'jobserve',
                'email_id': email.get('id'),
                'date_found': email.get('date'),
                'subject': subject,
            }
            
            # Extract job title from subject (usually first part)
            parts = subject.split(' - ')
            if len(parts) > 0:
                job['title'] = parts[0].strip()
            if len(parts) > 1:
                job['company'] = parts[1].strip()
            if len(parts) > 2:
                job['location'] = parts[2].strip()
            
            # Extract rate (pattern: £XXX/day or £XXX,XXX)
            rate_match = re.search(r'£([\d,]+)(?:/day|/d)?', body)
            if rate_match:
                job['rate'] = rate_match.group(1)
            
            # Extract duration (pattern: X months, 12 weeks, etc.)
            duration_match = re.search(r'(\d+\s*(?:months?|weeks?|days?))', body, re.IGNORECASE)
            if duration_match:
                job['duration'] = duration_match.group(1)
            
            # Check for IR35 status
            if 'outside ir35' in body.lower():
                job['ir35'] = 'Outside IR35'
            elif 'inside ir35' in body.lower():
                job['ir35'] = 'Inside IR35'
            else:
                job['ir35'] = 'Not specified'
            
            # Store full body for scoring
            job['full_spec'] = body
            job['reference'] = self._extract_reference(body, subject)
            
            return job
        
        except Exception as e:
            logger.error(f"Error parsing JobServe email: {e}")
            return None
    
    def _extract_reference(self, body: str, subject: str) -> str:
        """Extract job reference number from email"""
        # Try to find pattern like "Ref: ABC123" or "Reference: 12345"
        match = re.search(r'(?:Ref|Reference)[:=]?\s*([A-Z0-9]+)', body, re.IGNORECASE)
        if match:
            return match.group(1)
        return 'N/A'
