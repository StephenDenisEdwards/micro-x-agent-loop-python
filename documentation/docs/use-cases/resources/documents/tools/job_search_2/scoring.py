"""Job scoring engine - heuristic-based (avoids LLM calls)"""

import re
import logging
from typing import Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """Weights for different scoring factors"""
    technology_match: float = 0.30
    seniority_match: float = 0.25
    rate_match: float = 0.20
    sector_match: float = 0.15
    location_match: float = 0.10


class JobScorer:
    """
    Score jobs against criteria using heuristic rules.
    No LLM calls - purely regex and keyword matching.
    """
    
    # Core tech stack from criteria
    CORE_TECHNOLOGIES = {
        '.net': ['.net', 'dotnet', '.net core', '.net 6', '.net 7', '.net 8', '.net 9', '.net 10'],
        'c#': ['c#', 'csharp', 'c-sharp'],
        'azure': ['azure', 'microsoft azure'],
        'python': ['python'],
        'microservices': ['microservices', 'microservice'],
        'blazor': ['blazor'],
        'ai/ml': ['ai', 'ml', 'machine learning', 'artificial intelligence', 'langchain', 'openai', 'rag', 'vector db'],
        'kubernetes': ['kubernetes', 'k8s'],
        'docker': ['docker', 'containers'],
    }
    
    # Seniority indicators
    SENIORITY_KEYWORDS = {
        'senior': ['senior', 'lead', 'principal', 'staff', 'architect', 'head of'],
        'mid': ['mid-level', 'middle', 'intermediate'],
        'junior': ['junior', 'graduate', 'entry level', 'intern'],
    }
    
    # Preferred sectors
    PREFERRED_SECTORS = {
        'healthcare': ['healthcare', 'medtech', 'biotech', 'medical', 'health', 'pharma'],
        'finance': ['finance', 'fintech', 'banking', 'financial', 'investment'],
        'legal': ['legal', 'legal tech', 'law'],
        'industrial': ['industrial', 'manufacturing', 'factory'],
        'energy': ['energy', 'utilities', 'oil', 'gas'],
    }
    
    # Avoid keywords
    AVOID_KEYWORDS = [
        'junior', 'graduate', 'intern', 'entry level',
        'vb6', 'classic asp', 'sharepoint', 'permanent only',
    ]
    
    def __init__(self, criteria: dict):
        self.criteria = criteria
        self.weights = ScoringWeights()
    
    def score_job(self, job: Dict) -> float:
        """
        Score a job 1-10 based on heuristic matching against criteria.
        Returns float between 1.0 and 10.0.
        """
        # Quick eliminate if has avoid keywords
        if self._has_avoid_keywords(job):
            logger.debug(f"Job excluded: contains avoid keywords")
            return 0.0
        
        scores = {
            'technology': self._score_technology(job),
            'seniority': self._score_seniority(job),
            'rate': self._score_rate(job),
            'sector': self._score_sector(job),
            'location': self._score_location(job),
        }
        
        # Calculate weighted score
        total = (
            scores['technology'] * self.weights.technology_match +
            scores['seniority'] * self.weights.seniority_match +
            scores['rate'] * self.weights.rate_match +
            scores['sector'] * self.weights.sector_match +
            scores['location'] * self.weights.location_match
        )
        
        # Bonus for special interests
        bonus = self._calculate_bonus(job)
        total = min(10.0, total + bonus)
        
        logger.debug(f"Job '{job.get('title', 'Unknown')}': "
                    f"tech={scores['technology']:.1f}, "
                    f"sen={scores['seniority']:.1f}, "
                    f"rate={scores['rate']:.1f}, "
                    f"sec={scores['sector']:.1f}, "
                    f"loc={scores['location']:.1f}, "
                    f"total={total:.1f}")
        
        return total
    
    def _has_avoid_keywords(self, job: Dict) -> bool:
        """Check if job contains any avoid keywords"""
        full_text = self._get_searchable_text(job)
        
        for keyword in self.AVOID_KEYWORDS:
            if keyword in full_text.lower():
                return True
        
        return False
    
    def _score_technology(self, job: Dict) -> float:
        """Score 0-10 based on technology match"""
        text = self._get_searchable_text(job)
        text_lower = text.lower()
        
        matches = 0
        max_matches = len(self.CORE_TECHNOLOGIES)
        
        for tech, keywords in self.CORE_TECHNOLOGIES.items():
            for keyword in keywords:
                if keyword in text_lower:
                    matches += 1
                    break  # Count this tech only once
        
        # Need at least 2-3 core tech matches
        if matches == 0:
            return 2.0
        elif matches == 1:
            return 4.0
        elif matches == 2:
            return 6.0
        elif matches == 3:
            return 8.0
        else:  # 4+
            return 10.0
    
    def _score_seniority(self, job: Dict) -> float:
        """Score 0-10 based on seniority level"""
        text = self._get_searchable_text(job)
        text_lower = text.lower()
        
        # Check senior/lead keywords
        for keyword in self.SENIORITY_KEYWORDS['senior']:
            if keyword in text_lower:
                return 10.0
        
        # Check junior/graduate keywords
        for keyword in self.SENIORITY_KEYWORDS['junior']:
            if keyword in text_lower:
                return 2.0
        
        # Mid-level
        for keyword in self.SENIORITY_KEYWORDS['mid']:
            if keyword in text_lower:
                return 6.0
        
        # Unknown - assume mid
        return 6.0
    
    def _score_rate(self, job: Dict) -> float:
        """Score 0-10 based on day rate"""
        rate_str = job.get('rate', '')
        
        if not rate_str:
            return 4.0  # No rate specified = moderate penalty
        
        # Extract numeric value
        numbers = re.findall(r'\d+', rate_str.replace(',', ''))
        if not numbers:
            return 4.0
        
        rate = int(numbers[0])
        
        # Scoring scale (£/day)
        if rate >= 600:
            return 10.0
        elif rate >= 500:
            return 8.0
        elif rate >= 400:
            return 6.0
        elif rate >= 300:
            return 4.0
        else:
            return 2.0
    
    def _score_sector(self, job: Dict) -> float:
        """Score 0-10 based on sector preference"""
        text = self._get_searchable_text(job)
        text_lower = text.lower()
        
        matches = 0
        
        for sector, keywords in self.PREFERRED_SECTORS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    matches += 1
                    break
        
        if matches == 0:
            return 5.0  # Neutral for unknown sector
        elif matches == 1:
            return 7.0
        else:  # 2+
            return 10.0
    
    def _score_location(self, job: Dict) -> float:
        """Score 0-10 based on location"""
        location = job.get('location', '').lower()
        job_type = job.get('job_type', '').lower()
        
        # Check for London or Remote UK
        if 'london' in location or 'london' in job_type:
            return 10.0
        
        if 'remote' in location or 'remote' in job_type:
            if 'uk' in location or 'uk' in job_type:
                return 10.0
            else:
                return 6.0  # Remote but not specified UK
        
        if 'hybrid' in location or 'hybrid' in job_type:
            if 'london' in location or 'uk' in location:
                return 9.0
            else:
                return 5.0
        
        # Unknown location
        return 4.0
    
    def _calculate_bonus(self, job: Dict) -> float:
        """Calculate bonus points for special interests"""
        text = self._get_searchable_text(job)
        text_lower = text.lower()
        
        bonus = 0.0
        
        # AI/ML bonus
        ai_keywords = ['ai', 'ml', 'machine learning', 'langchain', 'openai', 'rag']
        if any(kw in text_lower for kw in ai_keywords):
            bonus += 0.5
        
        # Healthcare domain bonus
        health_keywords = ['healthcare', 'medical', 'fhir', 'hl7', 'gdpr', 'pharma']
        if any(kw in text_lower for kw in health_keywords):
            bonus += 0.5
        
        # Outside IR35 bonus
        if 'outside ir35' in text_lower:
            bonus += 0.5
        
        # Architecture/design focus
        arch_keywords = ['architect', 'design', 'architecture', 'solution design']
        if any(kw in text_lower for kw in arch_keywords):
            bonus += 0.3
        
        return min(1.5, bonus)  # Cap bonus at 1.5
    
    def _get_searchable_text(self, job: Dict) -> str:
        """Combine all textual fields for searching"""
        parts = [
            job.get('title', ''),
            job.get('company', ''),
            job.get('location', ''),
            job.get('full_spec', ''),
            job.get('subject', ''),
        ]
        return ' '.join(str(p) for p in parts if p)
