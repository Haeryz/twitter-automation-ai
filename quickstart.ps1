# Twitter Automation AI - Quick Start Script
# This script helps you get started quickly

Write-Host "🚀 Twitter Automation AI - Setup Checker" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Check if virtual environment is activated
if ($env:VIRTUAL_ENV) {
    Write-Host "✅ Virtual environment is activated" -ForegroundColor Green
} else {
    Write-Host "⚠️  Virtual environment is NOT activated" -ForegroundColor Yellow
    Write-Host "   Run: .\venv\Scripts\Activate.ps1`n" -ForegroundColor Yellow
    exit
}

# Check Python version
Write-Host "`n📌 Checking Python version..." -ForegroundColor Cyan
$pythonVersion = python --version
Write-Host "   $pythonVersion" -ForegroundColor Green

# Check if .env exists
Write-Host "`n📌 Checking .env file..." -ForegroundColor Cyan
if (Test-Path ".env") {
    Write-Host "   ✅ .env file exists" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  .env file not found" -ForegroundColor Yellow
    Write-Host "   Creating from template..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "   ✅ Created .env file - Please edit it with your API keys!" -ForegroundColor Green
}

# Check if accounts.json exists
Write-Host "`n📌 Checking accounts.json..." -ForegroundColor Cyan
if (Test-Path "config\accounts.json") {
    Write-Host "   ✅ accounts.json exists" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  accounts.json not found" -ForegroundColor Yellow
    Write-Host "   Please create it from the template!" -ForegroundColor Yellow
    Write-Host "   Template available at: config\accounts.json.template`n" -ForegroundColor Yellow
}

# Check if cookies file exists
Write-Host "`n📌 Checking cookie files..." -ForegroundColor Cyan
$cookieFiles = Get-ChildItem -Path "config" -Filter "*cookies*.json" -ErrorAction SilentlyContinue
if ($cookieFiles.Count -gt 0) {
    Write-Host "   ✅ Found $($cookieFiles.Count) cookie file(s)" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  No cookie files found" -ForegroundColor Yellow
    Write-Host "   Template available at: config\my_account_cookies.json.template`n" -ForegroundColor Yellow
}

# Check configuration
Write-Host "`n📌 Testing configuration..." -ForegroundColor Cyan
$configTest = python -c "from src.core.config_loader import ConfigLoader; config = ConfigLoader(); print('✅ Configuration loaded successfully!')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "   $configTest" -ForegroundColor Green
} else {
    Write-Host "   ❌ Configuration error:" -ForegroundColor Red
    Write-Host "   $configTest`n" -ForegroundColor Red
}

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "📋 Setup Checklist:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "1. ✅ Python and venv configured" -ForegroundColor Green
Write-Host "2. Edit .env with your API keys" -ForegroundColor Yellow
Write-Host "3. Create config\accounts.json from template" -ForegroundColor Yellow
Write-Host "4. Export Twitter cookies and save to config\" -ForegroundColor Yellow
Write-Host "5. Run: python src\main.py`n" -ForegroundColor Yellow

Write-Host "📚 For detailed instructions, see: SETUP_GUIDE.md`n" -ForegroundColor Cyan
