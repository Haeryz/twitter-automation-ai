# 🚀 Complete Setup Guide for Twitter Automation AI

## ✅ Prerequisites Check
- [x] Python 3.12.3 installed
- [x] pip 25.2 available
- [x] Virtual environment created
- [x] Dependencies installed

---

## 📝 Step-by-Step Setup Instructions

### 1. ✅ Virtual Environment (COMPLETED)
Your virtual environment has been created at `venv/` and is ready to use.

To activate it manually in future sessions:
```powershell
.\venv\Scripts\Activate.ps1
```

### 2. ✅ Dependencies Installation (COMPLETED)
All required packages have been installed:
- selenium
- webdriver-manager
- fake-headers
- pydantic
- langchain-google-genai
- openai
- requests
- python-dotenv
- undetected-chromedriver
- selenium-stealth

### 3. 🔑 API Keys Setup

#### Option A: Using .env file (Recommended for security)
1. Copy the example file:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and add your API keys:
   ```env
   GEMINI_API_KEY=your_actual_gemini_key_here
   OPENAI_API_KEY=your_actual_openai_key_here
   ```

3. Get API keys from:
   - **Google Gemini**: https://aistudio.google.com/app/apikey (Free tier available)
   - **OpenAI**: https://platform.openai.com/api-keys (Requires payment)

#### Option B: Direct in settings.json
Edit `config/settings.json` and replace the placeholder values in the `api_keys` section.

### 4. 🍪 Twitter Account Cookies Setup

#### How to Get Your Twitter Cookies:

**Method 1: Using Browser Extension (Recommended)**
1. Install "EditThisCookie" extension:
   - Chrome: https://chrome.google.com/webstore/detail/editthiscookie/
   - Firefox: https://addons.mozilla.org/en-US/firefox/addon/cookie-editor/

2. Login to https://x.com with your Twitter account

3. Click the extension icon and export cookies

4. Filter for these important cookies:
   - `auth_token` (Required)
   - `ct0` (Required - CSRF token)

5. Save as JSON file in `config/` folder (e.g., `config/your_account_cookies.json`)

**Method 2: Manual from DevTools**
1. Login to https://x.com
2. Press F12 to open DevTools
3. Go to Application/Storage → Cookies → https://x.com
4. Find and copy values for:
   - `auth_token`
   - `ct0`
5. Create a JSON file with this structure:
   ```json
   [
     {
       "name": "auth_token",
       "value": "YOUR_AUTH_TOKEN_VALUE",
       "domain": ".x.com",
       "path": "/",
       "expires": 1754092800,
       "httpOnly": true,
       "secure": true,
       "sameSite": "Lax"
     },
     {
       "name": "ct0",
       "value": "YOUR_CSRF_TOKEN_VALUE",
       "domain": ".x.com",
       "path": "/",
       "expires": 1754092800,
       "httpOnly": false,
       "secure": true,
       "sameSite": "Lax"
     }
   ]
   ```

6. Save to `config/your_account_cookies.json`

### 5. ⚙️ Configure accounts.json

Edit `config/accounts.json`:

```json
[
  {
    "account_id": "your_unique_account_id",
    "is_active": true,
    "cookie_file_path": "config/your_account_cookies.json",
    "proxy": null,
    
    "post_to_community": false,
    "community_id": null,
    "community_name": null,
    
    "target_keywords_override": [
      "AI",
      "Machine Learning",
      "Technology"
    ],
    
    "competitor_profiles_override": [
      "https://x.com/OpenAI",
      "https://x.com/GoogleAI"
    ],
    
    "llm_settings_override": {
      "service_preference": "gemini",
      "model_name_override": "gemini-2.5-flash",
      "max_tokens": 1000,
      "temperature": 0.7
    },
    
    "action_config_override": {
      "enable_competitor_reposts": true,
      "max_posts_per_competitor_run": 2,
      "enable_keyword_replies": true,
      "max_replies_per_keyword_run": 3,
      "enable_liking_tweets": true,
      "max_likes_per_run": 5
    }
  }
]
```

**Important Fields:**
- `account_id`: Unique name for your account (e.g., "my_main_account")
- `cookie_file_path`: Path to your cookie file
- `target_keywords_override`: Keywords to search and engage with
- `competitor_profiles_override`: Twitter profiles to scrape content from
- `service_preference`: "gemini" or "openai" (recommend gemini for free tier)

### 6. 🌐 Browser Setup

The project works with Chrome or Firefox. For best results:

**Option 1: Chrome (Recommended - Better Stealth)**
- Make sure Chrome is installed
- Edit `config/settings.json`:
  ```json
  "browser_settings": {
    "type": "chrome",
    "use_undetected_chromedriver": true,
    "enable_stealth": true,
    "headless": false
  }
  ```

**Option 2: Firefox**
- Default configuration uses Firefox
- No additional setup needed

### 7. 🔍 Quick Configuration Check

Run this command to verify your setup:
```powershell
D:/Side/twitter-automation-ai/venv/Scripts/python.exe -c "from src.core.config_loader import ConfigLoader; config = ConfigLoader(); print('✅ Configuration loaded successfully!')"
```

### 8. 🚀 Running the Application

**First Time Run (Recommended - Not Headless):**
```powershell
D:/Side/twitter-automation-ai/venv/Scripts/python.exe src/main.py
```

This will:
1. Load cookies and authenticate
2. Start automation based on your config
3. Show browser window for monitoring

**Production Run (Headless):**
1. Edit `config/settings.json` and set `"headless": true`
2. Run the same command

### 9. 📊 Monitoring

**Logs Location:**
- Console output: Real-time logs
- Account metrics: `data/metrics/<account_id>.json`
- Detailed logs: `logs/accounts/<account_id>.jsonl`

**What to Watch:**
- Check if cookies are valid
- Monitor for rate limits
- Verify actions are being performed

---

## 🎯 Quick Start Checklist

- [ ] Activate virtual environment: `.\venv\Scripts\Activate.ps1`
- [ ] Get API key from Google Gemini (free): https://aistudio.google.com/app/apikey
- [ ] Add API key to `.env` file
- [ ] Export Twitter cookies using browser extension
- [ ] Save cookies to `config/your_cookies.json`
- [ ] Update `config/accounts.json` with your account details
- [ ] Update `target_keywords_override` with topics you want to engage with
- [ ] Update `competitor_profiles_override` with Twitter accounts to scrape
- [ ] Run: `D:/Side/twitter-automation-ai/venv/Scripts/python.exe src/main.py`

---

## 🆘 Troubleshooting

### Cookies Not Working
- Make sure you're logged in to x.com before exporting
- Export ALL cookies, not just auth_token and ct0
- Check cookie expiration dates

### API Key Errors
- Verify API key is correct (no extra spaces)
- Check you have credits/quota available
- For Gemini, ensure API is enabled in Google Cloud Console

### Browser Driver Issues
- webdriver-manager should auto-download drivers
- If fails, install Chrome/Firefox manually
- Check internet connection for driver download

### Module Import Errors
- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`

### Rate Limiting
- Increase delays in `action_config`
- Reduce `max_posts_per_run`, `max_likes_per_run`, etc.
- Use proxies (optional)

---

## 📚 Additional Resources

- **Full Documentation**: Read `README.md`
- **Configuration Reference**: See `docs/CONFIG_REFERENCE.md`
- **Preset Configurations**: Check `presets/` folder for examples
- **Community**: Open issues on GitHub for help

---

## 🔒 Security Best Practices

1. **Never commit** `.env` or cookie files to git
2. Use `.gitignore` (already configured)
3. Rotate API keys periodically
4. Use separate Twitter accounts for testing
5. Monitor your Twitter account for unusual activity
6. Start with conservative settings (low max_posts, high delays)

---

## 🎉 You're Ready!

Your environment is fully set up. Follow the checklist above to configure your API keys and cookies, then run the application!

For questions or issues, refer to the README.md or open an issue on GitHub.
