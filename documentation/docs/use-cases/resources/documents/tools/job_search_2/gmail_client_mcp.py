"""
Gmail client using MCP (Message Passing Protocol) for actual implementation.

This replaces gmail_client.py when MCP servers are available.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from mcp_client import GmailMCPClient, create_gmail_client

logger = logging.getLogger(__name__)


class GmailClientMCP:
    """Gmail client using MCP protocol for stdio-based communication"""
    
    def __init__(self, config: dict, mcp_client: Optional[GmailMCPClient] = None):
        self.config = config
        self.mcp = mcp_client or create_gmail_client()
        self.is_connected = False
    
    def connect(self) -> bool:
        """Establish connection to Gmail MCP server"""
        self.is_connected = self.mcp.connect()
        if self.is_connected:
            logger.info("Connected to Gmail MCP server")
        else:
            logger.error("Failed to connect to Gmail MCP server")
        return self.is_connected
    
    def disconnect(self):
        """Close Gmail MCP connection"""
        self.mcp.disconnect()
        self.is_connected = False
    
    def search_jobserve_last_24h(self) -> List[Dict]:
        """
        Search Gmail for JobServe emails from last 24 hours via MCP.
        
        Returns:
            List of email dicts with id, from, subject, body, date
        """
        if not self.is_connected:
            logger.warning("Not connected to Gmail MCP server")
            return []
        
        # Calculate date range
        now = datetime.utcnow()
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Search query: from JobServe in last 24 hours
        query = f'from:jobserve after:{yesterday}'
        
        logger.info(f"Searching Gmail: {query}")
        
        results = self.mcp.search(query, max_results=50)
        if not results:
            logger.info("No JobServe emails found in last 24 hours")
            return []
        
        emails = []
        for result in results:
            message_id = result.get('id')
            
            # Fetch full email content
            full_email = self.mcp.read(message_id)
            if full_email:
                emails.append(full_email)
        
        logger.info(f"Retrieved {len(emails)} JobServe emails")
        return emails
    
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
        
        logger.info(f"Extracted {len(jobs)} jobs from {len(emails)} emails")
        return jobs
    
    def _parse_jobserve_email(self, email: Dict) -> Optional[Dict]:
        """
        Parse a single JobServe email and extract job details.
        
        Email structure from MCP gmail_read:
        {
            'id': message_id,
            'from': sender@...,
            'subject': email subject,
            'body': full email body (text),
            'date': ISO date string,
            'snippet': short preview,
        }
        """
        try:
            body = email.get('body', '')
            subject = email.get('subject', '')
            date_str = email.get('date', '')
            
            job = {
                'source': 'jobserve',
                'email_id': email.get('id'),
                'date_found': date_str,
                'subject': subject,
            }
            
            # Extract job title from subject (usually first part before company/location)
            parts = subject.split(' - ')
            if len(parts) > 0:
                job['title'] = parts[0].strip()
            if len(parts) > 1:
                job['company'] = parts[1].strip()
            if len(parts) > 2:
                job['location'] = parts[2].strip()
            
            # Extract rate (pattern: £XXX/day, £XXX-XXX/day, £XXX,XXX)
            rate_match = re.search(r'£([\d,\-]+)(?:\s*/\s*day|/d)?', body)
            if rate_match:
                job['rate'] = rate_match.group(1).strip()
            
            # Extract duration (pattern: X months, 12 weeks, etc.)
            duration_match = re.search(
                r'(?:contract|duration|length).*?(\d+\s*(?:months?|weeks?|days?))',
                body,
                re.IGNORECASE | re.DOTALL
            )
            if not duration_match:
                # Try simpler pattern
                duration_match = re.search(r'(\d+\s*(?:months?|weeks?|days?))', body)
            
            if duration_match:
                job['duration'] = duration_match.group(1).strip()
            
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
            
            logger.debug(f"Parsed job: {job.get('title', 'Unknown')} - Score pending")
            return job
        
        except Exception as e:
            logger.error(f"Error parsing JobServe email: {e}")
            return None
    
    def _extract_reference(self, body: str, subject: str) -> str:
        """Extract job reference number from email"""
        # Try to find pattern like "Ref: ABC123" or "Reference: 12345" or "JX12345"
        patterns = [
            r'(?:Ref|Reference)[:=]?\s*([A-Z0-9]+)',
            r'\b(JX\d+)\b',
            r'\b(J[0-9]{5,})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Try to extract from subject as fallback
        match = re.search(r'(?:Ref|Ref#):\s*([A-Z0-9]+)', subject)
        if match:
            return match.group(1)
        
        return 'N/A'
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
