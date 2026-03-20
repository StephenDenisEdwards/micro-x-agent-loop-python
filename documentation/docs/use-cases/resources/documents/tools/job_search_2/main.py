#!/usr/bin/env python3
"""
Job Search Console App - Main Entry Point

Searches Gmail for JobServe emails and LinkedIn for contract roles,
scores them against search criteria, and generates a markdown report.

Avoids LLM calls where possible - uses direct API access and heuristic scoring.
"""

import json
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import load_config
from gmail_client import GmailClient
from linkedin_client import LinkedInClient
from scoring import JobScorer
from report_generator import ReportGenerator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_criteria() -> dict:
    """Load job search criteria from criteria.txt"""
    criteria_path = Path(__file__).parent.parent.parent / 'documents' / 'job-search-criteria.txt'
    if not criteria_path.exists():
        logger.error(f"Criteria file not found: {criteria_path}")
        sys.exit(1)
    
    with open(criteria_path, 'r') as f:
        return {'raw_text': f.read()}


def main():
    """Main entry point"""
    logger.info("Starting job search agent...")
    
    # Load configuration
    config = load_config()
    criteria = load_criteria()
    
    # Initialize clients
    gmail = GmailClient(config)
    linkedin = LinkedInClient(config)
    scorer = JobScorer(criteria)
    
    # Search Gmail for JobServe emails (last 24 hours)
    logger.info("Searching Gmail for JobServe emails...")
    jobserve_emails = gmail.search_jobserve_last_24h()
    jobserve_jobs = gmail.extract_jobs_from_emails(jobserve_emails)
    logger.info(f"Found {len(jobserve_jobs)} JobServe jobs")
    
    # Search LinkedIn for contract roles
    logger.info("Searching LinkedIn for contract roles...")
    linkedin_jobs = linkedin.search_contract_roles()
    logger.info(f"Found {len(linkedin_jobs)} LinkedIn jobs")
    
    # Score all jobs
    logger.info("Scoring jobs...")
    all_jobs = jobserve_jobs + linkedin_jobs
    scored_jobs = []
    
    for job in all_jobs:
        score = scorer.score_job(job)
        if score >= 5:  # Only include jobs scoring 5+
            job['score'] = score
            scored_jobs.append(job)
    
    logger.info(f"Jobs scoring 5+/10: {len(scored_jobs)}")
    
    # Sort by score
    scored_jobs.sort(key=lambda x: x['score'], reverse=True)
    
    # Generate report
    logger.info("Generating report...")
    generator = ReportGenerator(scored_jobs, criteria)
    report_path = generator.generate()
    
    logger.info(f"Report saved to {report_path}")
    print(f"\n✓ Report generated: {report_path}")


if __name__ == '__main__':
    main()
