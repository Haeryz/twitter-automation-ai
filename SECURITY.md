# Security Policy

## 🔐 Sensitive Data Protection

This project handles sensitive data including Twitter authentication cookies, API keys, and personal account information. Please follow these guidelines to keep your data secure.

## Files That Must NEVER Be Committed

### 🔴 Critical - Contains Authentication & API Keys

1. **`config/accounts.json`**
   - Contains account configurations
   - May include account IDs and settings
   - **Status:** Listed in `.gitignore`
   - **Template:** Use `config/accounts.json.template`

2. **`config/settings.json`**
   - Contains API keys for Gemini, OpenAI, Azure
   - Contains automation settings
   - **Status:** Listed in `.gitignore`
   - **Template:** Use `config/settings.json.template`

3. **`config/*_cookies.json`**
   - Contains Twitter authentication cookies
   - Includes session tokens and auth credentials
   - **Status:** Listed in `.gitignore`
   - **Example:** `data/cookies/dummy_cookies_example.json` (safe template)

4. **`.env`** (if you create one)
   - Environment variables with API keys
   - **Status:** Listed in `.gitignore`

### ⚠️ User-Generated Data

5. **`data/metrics/*.json`**
   - Per-account activity metrics
   - **Status:** Listed in `.gitignore`
   - **Location:** `data/metrics/`

6. **`data/style_memory/*.json`**
   - Twitter handles and posting patterns
   - Real tweet IDs and URLs
   - **Status:** Listed in `.gitignore`
   - **Location:** `data/style_memory/`

7. **`logs/accounts/*.jsonl`**
   - Detailed activity logs with tweet IDs
   - Action history
   - **Status:** Listed in `.gitignore`
   - **Location:** `logs/accounts/`

8. **`processed_tweets_log.csv`**
   - Tweet interaction history
   - **Status:** Listed in `.gitignore`

9. **`media_files/`**
   - Downloaded media from Twitter
   - **Status:** Listed in `.gitignore`

10. **`data/proxy_pools_state.json`**
    - Proxy rotation state
    - **Status:** Listed in `.gitignore`

## Safe Files (Can Be Committed)

### ✅ Templates & Examples

- `config/accounts.json.template` - Template for accounts configuration
- `config/settings.json.template` - Template for settings configuration
- `data/cookies/dummy_cookies_example.json` - Example cookie structure
- `data/proxies/dummy_proxies.json` - Example proxy configuration
- `presets/**/*.json` - Preset configurations (no real data)

### ✅ Directory Markers

- `.gitkeep` files in empty directories
- Ensures directory structure is maintained in Git

## Before Committing

### Checklist

- [ ] Run `git status` and verify no sensitive files are staged
- [ ] Check that `.gitignore` is working correctly
- [ ] Ensure only template files are in `config/` directory
- [ ] Verify no real API keys are in any committed files
- [ ] Check that no real Twitter handles or tweet IDs are in commits

### Test Your .gitignore

```bash
# This should show ONLY template files and safe examples
git status

# This should NOT show:
# - config/accounts.json
# - config/settings.json
# - config/*_cookies.json
# - data/metrics/*.json
# - logs/accounts/*.jsonl
```

## What To Do If You Accidentally Commit Sensitive Data

### 1. Immediately Rotate Credentials

- **API Keys:** Generate new keys immediately
  - Gemini: https://makersuite.google.com/app/apikey
  - OpenAI: https://platform.openai.com/api-keys
- **Twitter Cookies:** Log out and log back in to invalidate sessions
- **Proxies:** Change proxy passwords if exposed

### 2. Remove From Git History

```bash
# Remove the file from git history (use with caution)
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch config/accounts.json" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (WARNING: rewrites history)
git push origin --force --all
```

**Better approach:** Use BFG Repo-Cleaner:
```bash
# Install BFG
# https://rtyley.github.io/bfg-repo-cleaner/

# Remove sensitive file
bfg --delete-files config/accounts.json

# Clean up
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push
git push origin --force --all
```

### 3. Report to Repository Owner

If this is a public repository, contact the repository owner immediately.

## API Key Security Best Practices

### Use Environment Variables

Instead of hardcoding in `config/settings.json`:

```bash
# Windows PowerShell
$env:GEMINI_API_KEY="your_key_here"

# Linux/macOS
export GEMINI_API_KEY="your_key_here"
```

The application checks environment variables before falling back to config files.

### Use .env File (Locally Only)

Create a `.env` file (already in `.gitignore`):

```env
GEMINI_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
RESI_PASS=your_proxy_password
```

## Cookie Security

### How to Get Cookies Safely

1. Install a cookie export extension (e.g., "EditThisCookie")
2. Log into Twitter/X
3. Export cookies for `x.com` domain
4. Save to `config/<account_name>_cookies.json`
5. **Never share or commit this file**

### Cookie Expiration

- Twitter cookies expire and need periodic renewal
- Monitor for authentication failures
- Re-export and update cookie files as needed

## Proxy Configuration

### Environment Variable Interpolation

Use environment variables in proxy URLs:

```json
{
  "proxy_pools": {
    "my_proxies": [
      "http://user:${PROXY_PASS}@proxy.example.com:8080"
    ]
  }
}
```

This keeps passwords out of config files.

## Reporting Security Issues

If you discover a security vulnerability in this project:

1. **Do NOT** open a public issue
2. Contact the repository maintainers privately
3. Provide detailed information about the vulnerability
4. Allow time for a fix before public disclosure

## Additional Resources

- [GitHub's guide to removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Twitter Developer Documentation](https://developer.twitter.com/en/docs)

## Questions?

If you have questions about what's safe to commit, check:
1. The `.gitignore` file
2. The templates in `config/` directory
3. The examples in `data/` directory
4. Open an issue (without including sensitive data)

---

**Remember:** When in doubt, DON'T commit it! It's easier to add files later than to remove them from Git history.
