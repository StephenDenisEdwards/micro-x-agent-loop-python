"""
MCP (Message Passing Protocol) Client for stdio-based servers.

This module provides a generic interface to connect to MCP servers
for Gmail, LinkedIn, and other data sources via stdio.
"""

import json
import logging
import subprocess
import sys
from typing import Optional, Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Generic MCP client for stdio-based communication.
    Manages process lifecycle and request/response handling.
    """
    
    def __init__(self, server_command: str, server_args: Optional[List[str]] = None):
        """
        Initialize MCP client.
        
        Args:
            server_command: Command to start the MCP server (e.g., "python", "node")
            server_args: Arguments to pass to server (e.g., ["script.py", "--port", "8000"])
        """
        self.server_command = server_command
        self.server_args = server_args or []
        self.process: Optional[subprocess.Popen] = None
        self.is_connected = False
    
    def connect(self) -> bool:
        """Start the MCP server process"""
        try:
            self.process = subprocess.Popen(
                [self.server_command] + self.server_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.is_connected = True
            logger.info(f"Connected to MCP server: {self.server_command}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            return False
    
    def disconnect(self):
        """Stop the MCP server process"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                logger.info("Disconnected from MCP server")
            except subprocess.TimeoutExpired:
                self.process.kill()
                logger.warning("MCP server killed (timeout)")
            finally:
                self.is_connected = False
    
    def call(self, method: str, params: Dict[str, Any]) -> Optional[Dict]:
        """
        Call a method on the MCP server.
        
        Args:
            method: Method name (e.g., "gmail_search", "linkedin_jobs")
            params: Method parameters
        
        Returns:
            Response dict or None on error
        """
        if not self.is_connected or not self.process:
            logger.error("Not connected to MCP server")
            return None
        
        request = {
            'method': method,
            'params': params,
        }
        
        try:
            # Send request
            self.process.stdin.write(json.dumps(request) + '\n')
            self.process.stdin.flush()
            
            # Read response
            response_line = self.process.stdout.readline()
            if not response_line:
                logger.error("No response from MCP server")
                return None
            
            response = json.loads(response_line)
            
            if 'error' in response:
                logger.error(f"MCP error: {response['error']}")
                return None
            
            return response.get('result')
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP response: {e}")
            return None
        except Exception as e:
            logger.error(f"MCP call failed: {e}")
            return None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


class GmailMCPClient(MCPClient):
    """MCP client wrapper for Gmail operations"""
    
    def search(self, query: str, max_results: int = 20) -> Optional[List[Dict]]:
        """Search Gmail with a query"""
        result = self.call('gmail_search', {
            'query': query,
            'maxResults': max_results,
        })
        return result
    
    def read(self, message_id: str) -> Optional[Dict]:
        """Read full email content by message ID"""
        result = self.call('gmail_read', {
            'messageId': message_id,
        })
        return result


class LinkedInMCPClient(MCPClient):
    """MCP client wrapper for LinkedIn operations"""
    
    def search_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        job_type: Optional[str] = None,
        experience_level: Optional[str] = None,
        date_since_posted: Optional[str] = None,
        limit: int = 10,
    ) -> Optional[List[Dict]]:
        """Search LinkedIn jobs"""
        params = {
            'keyword': keyword,
            'limit': limit,
        }
        if location:
            params['location'] = location
        if job_type:
            params['jobType'] = job_type
        if experience_level:
            params['experienceLevel'] = experience_level
        if date_since_posted:
            params['dateSincePosted'] = date_since_posted
        
        result = self.call('linkedin_jobs', params)
        return result
    
    def get_job_details(self, url: str) -> Optional[Dict]:
        """Get full job details from job URL"""
        result = self.call('linkedin_job_detail', {
            'url': url,
        })
        return result


def create_gmail_client(command: Optional[str] = None) -> GmailMCPClient:
    """Factory function to create Gmail MCP client"""
    # Try to detect MCP server command
    if not command:
        # Look for known MCP server locations
        candidates = [
            'mcp-gmail',
            'python -m mcp_gmail',
            'node mcp-gmail/index.js',
        ]
        for candidate in candidates:
            try:
                subprocess.run(
                    candidate.split(),
                    capture_output=True,
                    timeout=2,
                )
                command = candidate
                break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        
        if not command:
            logger.warning("Could not auto-detect Gmail MCP server")
            command = 'mcp-gmail'
    
    return GmailMCPClient(command)


def create_linkedin_client(command: Optional[str] = None) -> LinkedInMCPClient:
    """Factory function to create LinkedIn MCP client"""
    if not command:
        candidates = [
            'mcp-linkedin',
            'python -m mcp_linkedin',
            'node mcp-linkedin/index.js',
        ]
        for candidate in candidates:
            try:
                subprocess.run(
                    candidate.split(),
                    capture_output=True,
                    timeout=2,
                )
                command = candidate
                break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        
        if not command:
            logger.warning("Could not auto-detect LinkedIn MCP server")
            command = 'mcp-linkedin'
    
    return LinkedInMCPClient(command)
