#!/usr/bin/env python3
"""
Setup script for Twitter Automation AI
This script initializes the configuration files from templates.
Run this after cloning the repository.
"""

import os
import shutil
import sys
from pathlib import Path

def print_header(message):
    """Print a formatted header message."""
    print(f"\n{'='*70}")
    print(f"  {message}")
    print(f"{'='*70}\n")

def print_success(message):
    """Print a success message."""
    print(f"✓ {message}")

def print_warning(message):
    """Print a warning message."""
    print(f"⚠ {message}")

def print_error(message):
    """Print an error message."""
    print(f"✗ {message}")

def setup_config_files():
    """Copy template config files to actual config files if they don't exist."""
    print_header("Setting up configuration files")
    
    config_dir = Path("config")
    
    # Check if config directory exists
    if not config_dir.exists():
        print_error(f"Config directory not found: {config_dir}")
        return False
    
    templates = [
        ("accounts.json.template", "accounts.json"),
        ("settings.json.template", "settings.json")
    ]
    
    for template_name, target_name in templates:
        template_path = config_dir / template_name
        target_path = config_dir / target_name
        
        # Check if template exists
        if not template_path.exists():
            print_error(f"Template not found: {template_path}")
            continue
        
        # Check if target already exists
        if target_path.exists():
            print_warning(f"Config file already exists: {target_name} (skipping)")
            continue
        
        # Copy template to target
        try:
            shutil.copy(template_path, target_path)
            print_success(f"Created: {target_name}")
        except Exception as e:
            print_error(f"Failed to create {target_name}: {e}")
            return False
    
    return True

def verify_directories():
    """Verify that all required directories exist."""
    print_header("Verifying directory structure")
    
    required_dirs = [
        "media_files",
        "data/metrics",
        "data/style_memory",
        "data/cookies",
        "data/proxies",
        "logs",
        "logs/accounts"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print_success(f"Directory exists: {dir_path}")
        else:
            print_warning(f"Directory missing: {dir_path} (will be created)")
            try:
                path.mkdir(parents=True, exist_ok=True)
                print_success(f"Created directory: {dir_path}")
            except Exception as e:
                print_error(f"Failed to create {dir_path}: {e}")
                all_exist = False
    
    return all_exist

def display_next_steps():
    """Display next steps for the user."""
    print_header("Setup Complete! Next Steps")
    
    print("""
1. CONFIGURE API KEYS:
   Edit config/settings.json and add your API keys:
   - Gemini API key (get from: https://makersuite.google.com/app/apikey)
   - OpenAI API key (optional, get from: https://platform.openai.com/api-keys)
   - Azure OpenAI credentials (optional)

2. SETUP TWITTER ACCOUNT(S):
   Edit config/accounts.json:
   - Change account_id to your desired identifier
   - Export your Twitter cookies using a browser extension like "EditThisCookie"
   - Save cookies to config/<your_account>_cookies.json
   - Update cookie_file_path in accounts.json
   - Configure keywords, competitor profiles, and action settings

3. INSTALL DEPENDENCIES:
   Run: pip install -r requirements.txt

4. TEST YOUR SETUP:
   Run: python src/main.py

5. (Optional) CONFIGURE PROXIES:
   - If using proxies, add them to config/settings.json under browser_settings.proxy
   - Or use proxy pools as shown in data/proxies/dummy_proxies.json

⚠ IMPORTANT SECURITY NOTES:
   - NEVER commit config/accounts.json or config/settings.json to Git
   - NEVER commit any *_cookies.json files
   - Keep your API keys secret
   - These files are already in .gitignore

For detailed documentation, see README.md and docs/CONFIG_REFERENCE.md
    """)

def main():
    """Main setup function."""
    print_header("Twitter Automation AI - Initial Setup")
    
    # Change to script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    print(f"Working directory: {os.getcwd()}")
    
    # Run setup steps
    success = True
    success &= setup_config_files()
    success &= verify_directories()
    
    if success:
        display_next_steps()
        print_success("Setup completed successfully!")
        return 0
    else:
        print_error("Setup completed with errors. Please review the messages above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
