# Quick Reference: accounts.json Configuration

## Minimal Configuration (Recommended for Beginners)

```json
[
  {
    "account_id": "my_account",
    "is_active": true,
    "cookie_file_path": "config/my_account_cookies.json",
    "proxy": null,
    
    "target_keywords_override": [
      "Artificial Intelligence",
      "Technology"
    ],
    
    "competitor_profiles_override": [
      "https://x.com/OpenAI"
    ],
    
    "llm_settings_override": {
      "service_preference": "gemini",
      "model_name_override": "gemini-2.5-flash"
    },
    
    "action_config_override": {
      "enable_liking_tweets": true,
      "max_likes_per_run": 5
    }
  }
]
```

## Conservative Configuration (Safe Testing)

```json
[
  {
    "account_id": "test_account",
    "is_active": true,
    "cookie_file_path": "config/test_cookies.json",
    
    "target_keywords_override": [
      "AI News"
    ],
    
    "competitor_profiles_override": [
      "https://x.com/OpenAI"
    ],
    
    "llm_settings_override": {
      "service_preference": "gemini",
      "temperature": 0.7
    },
    
    "action_config_override": {
      "min_delay_between_actions_seconds": 180,
      "max_delay_between_actions_seconds": 360,
      "enable_liking_tweets": true,
      "max_likes_per_run": 3,
      "enable_keyword_replies": false,
      "enable_competitor_reposts": false
    }
  }
]
```

## Aggressive Growth Configuration

```json
[
  {
    "account_id": "growth_account",
    "is_active": true,
    "cookie_file_path": "config/growth_cookies.json",
    
    "target_keywords_override": [
      "AI", "Machine Learning", "Deep Learning", "LLM", "ChatGPT"
    ],
    
    "competitor_profiles_override": [
      "https://x.com/OpenAI",
      "https://x.com/GoogleAI",
      "https://x.com/AnthropicAI"
    ],
    
    "llm_settings_override": {
      "service_preference": "gemini",
      "model_name_override": "gemini-2.5-flash",
      "temperature": 0.75
    },
    
    "action_config_override": {
      "min_delay_between_actions_seconds": 90,
      "max_delay_between_actions_seconds": 240,
      
      "enable_competitor_reposts": true,
      "max_posts_per_competitor_run": 2,
      "min_likes_for_repost_candidate": 20,
      
      "enable_keyword_replies": true,
      "max_replies_per_keyword_run": 5,
      
      "enable_liking_tweets": true,
      "max_likes_per_run": 10,
      
      "enable_relevance_filter_competitor_reposts": true,
      "relevance_threshold_competitor_reposts": 0.45
    }
  }
]
```

## Multi-Account Configuration

```json
[
  {
    "account_id": "personal_account",
    "is_active": true,
    "cookie_file_path": "config/personal_cookies.json",
    "target_keywords_override": ["AI", "Tech"],
    "competitor_profiles_override": ["https://x.com/OpenAI"],
    "llm_settings_override": {
      "service_preference": "gemini"
    },
    "action_config_override": {
      "enable_liking_tweets": true,
      "max_likes_per_run": 5
    }
  },
  {
    "account_id": "business_account",
    "is_active": true,
    "cookie_file_path": "config/business_cookies.json",
    "target_keywords_override": ["B2B SaaS", "Enterprise AI"],
    "competitor_profiles_override": ["https://x.com/Salesforce"],
    "llm_settings_override": {
      "service_preference": "openai",
      "model_name_override": "gpt-4"
    },
    "action_config_override": {
      "enable_competitor_reposts": true,
      "max_posts_per_competitor_run": 1
    }
  },
  {
    "account_id": "test_account",
    "is_active": false,
    "cookie_file_path": "config/test_cookies.json",
    "target_keywords_override": ["Test"],
    "competitor_profiles_override": ["https://x.com/Test"]
  }
]
```

## Community Posting Configuration

```json
[
  {
    "account_id": "community_account",
    "is_active": true,
    "cookie_file_path": "config/community_cookies.json",
    
    "post_to_community": true,
    "community_id": "1234567890123456789",
    "community_name": "AI Enthusiasts",
    
    "target_keywords_override": [
      "AI Community",
      "AI Discussion"
    ],
    
    "competitor_profiles_override": [
      "https://x.com/OpenAI"
    ],
    
    "llm_settings_override": {
      "service_preference": "gemini"
    },
    
    "action_config_override": {
      "enable_community_engagement": true,
      "enable_community_likes": true,
      "max_community_engagements_per_run": 5
    }
  }
]
```

## Field Explanations

### Required Fields
- `account_id`: Unique identifier (use descriptive names)
- `is_active`: `true` to enable, `false` to disable
- `cookie_file_path`: Path to cookie JSON file

### Optional Core Fields
- `proxy`: Proxy URL (e.g., "http://user:pass@host:port") or null
- `post_to_community`: `true` to post to community instead of timeline
- `community_id`: Twitter community ID (preferred)
- `community_name`: Community display name (fallback)

### Content Configuration
- `target_keywords_override`: Array of keywords to search/engage
- `competitor_profiles_override`: Array of Twitter URLs to scrape
- `news_sites_override`: Array of news URLs (optional)
- `research_paper_sites_override`: Array of research URLs (optional)

### LLM Settings
- `service_preference`: "gemini" or "openai"
- `model_name_override`: Model name (e.g., "gemini-2.5-flash", "gpt-4")
- `max_tokens`: Response length limit
- `temperature`: Creativity (0.0 = deterministic, 1.0 = creative)

### Action Configuration
**Timing:**
- `min_delay_between_actions_seconds`: Minimum wait (default: 60)
- `max_delay_between_actions_seconds`: Maximum wait (default: 180)

**Competitor Actions:**
- `enable_competitor_reposts`: Repost from competitors
- `max_posts_per_competitor_run`: Limit per run
- `min_likes_for_repost_candidate`: Minimum likes threshold
- `min_retweets_for_repost_candidate`: Minimum retweets threshold
- `competitor_post_interaction_type`: "repost", "retweet", or "quote"

**Keyword Engagement:**
- `enable_keyword_replies`: Reply to keyword tweets
- `max_replies_per_keyword_run`: Reply limit
- `reply_only_to_recent_tweets_hours`: Age filter (24 = last day)
- `enable_keyword_retweets`: Retweet keyword tweets
- `max_retweets_per_keyword_run`: Retweet limit

**Liking:**
- `enable_liking_tweets`: Like tweets
- `max_likes_per_run`: Like limit
- `like_tweets_from_feed`: Like from home feed
- `like_tweets_from_keywords`: Keywords for liking (or null to use target_keywords)

**Relevance Filtering:**
- `enable_relevance_filter_competitor_reposts`: Filter competitor content
- `relevance_threshold_competitor_reposts`: Threshold (0.0-1.0)
- `enable_relevance_filter_likes`: Filter likes
- `relevance_threshold_likes`: Threshold (0.0-1.0)
- `enable_relevance_filter_keyword_replies`: Filter replies
- `relevance_threshold_keyword_replies`: Threshold (0.0-1.0)

**Community Engagement:**
- `enable_community_engagement`: Engage with community posts
- `enable_community_likes`: Like community posts
- `enable_community_retweets`: Retweet community posts
- `max_community_engagements_per_run`: Total community actions
- `enable_community_replies`: Reply to community posts
- `max_community_replies_per_run`: Community reply limit

## Tips

### Starting Safe
1. Set `is_active: true` for only ONE account first
2. Use low limits (max_likes_per_run: 3-5)
3. Use long delays (180-360 seconds)
4. Disable aggressive features initially

### Testing
1. Use a test account first
2. Set `headless: false` in settings.json to watch
3. Monitor logs in console
4. Check data/metrics/<account_id>.json for stats

### Scaling Up
1. Increase limits gradually
2. Add more keywords over time
3. Enable more features one at a time
4. Monitor for rate limits or blocks

### Multiple Accounts
1. Use unique cookie files per account
2. Consider proxies for multiple accounts
3. Stagger run times if running simultaneously
4. Different strategies per account (diversify)

## Common Patterns

### Read-Only (Monitoring)
```json
"action_config_override": {
  "enable_competitor_reposts": false,
  "enable_keyword_replies": false,
  "enable_liking_tweets": false
}
```

### Engagement Only (No Posting)
```json
"action_config_override": {
  "enable_liking_tweets": true,
  "max_likes_per_run": 10,
  "enable_keyword_replies": false,
  "enable_competitor_reposts": false
}
```

### Growth Mode (Aggressive)
```json
"action_config_override": {
  "enable_competitor_reposts": true,
  "enable_keyword_replies": true,
  "enable_liking_tweets": true,
  "max_posts_per_competitor_run": 3,
  "max_replies_per_keyword_run": 5,
  "max_likes_per_run": 15
}
```

### Brand Safe (Conservative)
```json
"action_config_override": {
  "enable_relevance_filter_competitor_reposts": true,
  "relevance_threshold_competitor_reposts": 0.6,
  "enable_competitor_reposts": true,
  "max_posts_per_competitor_run": 1,
  "min_likes_for_repost_candidate": 50
}
```
