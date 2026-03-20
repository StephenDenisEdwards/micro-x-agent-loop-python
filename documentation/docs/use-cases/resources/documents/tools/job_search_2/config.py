"""Configuration loader for job search app"""

import os
import json
from pathlib import Path
from typing import Optional


def load_config() -> dict:
    """
    Load configuration from config.json or environment variables.
    Supports MCP server connections.
    """
    config_path = Path(__file__).parent / 'config.json'
    
    config = {
        'gmail': {
            'enabled': True,  # Gmail via MCP
        },
        'linkedin': {
            'enabled': True,  # LinkedIn via MCP
        },
        'output_dir': str(Path(__file__).parent.parent.parent / 'documents'),
    }
    
    # Load from config.json if it exists
    if config_path.exists():
        with open(config_path, 'r') as f:
            user_config = json.load(f)
            config.update(user_config)
    
    # Override with environment variables
    if os.getenv('JOB_SEARCH_OUTPUT_DIR'):
        config['output_dir'] = os.getenv('JOB_SEARCH_OUTPUT_DIR')
    
    return config
