# Twitter Automation AI - Setup Script for Windows
# Run this script after cloning the repository

Write-Host "`n======================================================================"
Write-Host "  Twitter Automation AI - Initial Setup"
Write-Host "======================================================================`n"

$currentDir = Get-Location
Write-Host "Working directory: $currentDir`n"

# Function to print colored messages
function Write-Success {
    param($message)
    Write-Host "✓ $message" -ForegroundColor Green
}

function Write-Warning {
    param($message)
    Write-Host "⚠ $message" -ForegroundColor Yellow
}

function Write-Error {
    param($message)
    Write-Host "✗ $message" -ForegroundColor Red
}

# Setup configuration files
Write-Host "`n======================================================================"
Write-Host "  Setting up configuration files"
Write-Host "======================================================================`n"

$configDir = "config"
if (-not (Test-Path $configDir)) {
    Write-Error "Config directory not found: $configDir"
    exit 1
}

$templates = @(
    @{Template = "accounts.json.template"; Target = "accounts.json"},
    @{Template = "settings.json.template"; Target = "settings.json"}
)

foreach ($file in $templates) {
    $templatePath = Join-Path $configDir $file.Template
    $targetPath = Join-Path $configDir $file.Target
    
    if (-not (Test-Path $templatePath)) {
        Write-Error "Template not found: $templatePath"
        continue
    }
    
    if (Test-Path $targetPath) {
        Write-Warning "Config file already exists: $($file.Target) (skipping)"
        continue
    }
    
    try {
        Copy-Item $templatePath $targetPath
        Write-Success "Created: $($file.Target)"
    }
    catch {
        Write-Error "Failed to create $($file.Target): $_"
        exit 1
    }
}

# Verify directories
Write-Host "`n======================================================================"
Write-Host "  Verifying directory structure"
Write-Host "======================================================================`n"

$requiredDirs = @(
    "media_files",
    "data\metrics",
    "data\style_memory",
    "data\cookies",
    "data\proxies",
    "logs",
    "logs\accounts"
)

foreach ($dir in $requiredDirs) {
    if (Test-Path $dir) {
        Write-Success "Directory exists: $dir"
    }
    else {
        Write-Warning "Directory missing: $dir (creating...)"
        try {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-Success "Created directory: $dir"
        }
        catch {
            Write-Error "Failed to create $dir: $_"
            exit 1
        }
    }
}

# Display next steps
Write-Host "`n======================================================================"
Write-Host "  Setup Complete! Next Steps"
Write-Host "======================================================================`n"

Write-Host @"

1. CONFIGURE API KEYS:
   Edit config\settings.json and add your API keys:
   - Gemini API key (get from: https://makersuite.google.com/app/apikey)
   - OpenAI API key (optional, get from: https://platform.openai.com/api-keys)
   - Azure OpenAI credentials (optional)

2. SETUP TWITTER ACCOUNT(S):
   Edit config\accounts.json:
   - Change account_id to your desired identifier
   - Export your Twitter cookies using a browser extension like "EditThisCookie"
   - Save cookies to config\<your_account>_cookies.json
   - Update cookie_file_path in accounts.json
   - Configure keywords, competitor profiles, and action settings

3. INSTALL DEPENDENCIES:
   Run: pip install -r requirements.txt

4. TEST YOUR SETUP:
   Run: python src\main.py

5. (Optional) CONFIGURE PROXIES:
   - If using proxies, add them to config\settings.json under browser_settings.proxy
   - Or use proxy pools as shown in data\proxies\dummy_proxies.json

"@

Write-Host "⚠ IMPORTANT SECURITY NOTES:" -ForegroundColor Yellow
Write-Host "   - NEVER commit config\accounts.json or config\settings.json to Git"
Write-Host "   - NEVER commit any *_cookies.json files"
Write-Host "   - Keep your API keys secret"
Write-Host "   - These files are already in .gitignore"
Write-Host ""
Write-Host "For detailed documentation, see README.md and docs\CONFIG_REFERENCE.md"
Write-Host ""

Write-Success "Setup completed successfully!"
Write-Host "`nPress any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
