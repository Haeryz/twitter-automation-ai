import asyncio
import logging
import sys
import os
import time
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

# Ensure src directory is in Python path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config_loader import ConfigLoader, PROJECT_ROOT
from core.browser_manager import BrowserManager
from core.llm_service import LLMService
from utils.logger import setup_logger
from utils.file_handler import FileHandler
from data_models import AccountConfig, TweetContent, LLMSettings, ScrapedTweet, ActionConfig
from features.scraper import TweetScraper
from features.publisher import TweetPublisher
from features.publisher.reply_generator import generate_guarded_reply, should_apply_style_profile
from features.publisher.style_utils import build_style_snapshot
from features.engagement import TweetEngagement
from features.analyzer import TweetAnalyzer
from utils.metrics import MetricsRecorder

# Initialize main config loader and logger
main_config_loader = ConfigLoader()
# Configure logging and get module logger
setup_logger(main_config_loader)
logger = logging.getLogger(__name__)

class TwitterOrchestrator:
    def __init__(self):
        self.config_loader = main_config_loader
        self.file_handler = FileHandler(self.config_loader)
        self.global_settings = self.config_loader.get_settings()
        self.accounts_data = self.config_loader.get_accounts_config()
        
        self.processed_action_keys = self.file_handler.load_processed_action_keys() # Load processed action keys
        # Analysis and decision config snapshots
        ta = self.global_settings.get('twitter_automation', {})
        self.analysis_config = ta.get('analysis_config', {})
        self.engagement_decision_cfg = ta.get('engagement_decision', {"enabled": False})

    @staticmethod
    def _is_own_tweet(user_handle: str, account: AccountConfig, browser_manager: BrowserManager) -> bool:
        """Return True if the given user_handle belongs to the current account.

        Compares against:
        - configured account.self_handles (if provided)
        - browser_manager.logged_in_handle (if detected)
        - account.account_id (as last-resort heuristic)
        """
        try:
            handle = (user_handle or "").strip().lstrip('@').lower()
            candidates = set()
            # Explicit self handles from config
            for h in (account.self_handles or []):
                if isinstance(h, str) and h.strip():
                    candidates.add(h.strip().lstrip('@').lower())
            # Runtime-detected handle from UI
            if getattr(browser_manager, 'logged_in_handle', None):
                candidates.add(str(browser_manager.logged_in_handle).strip().lstrip('@').lower())
            # Heuristic fallback: account_id (in case user set it to the handle)
            if isinstance(account.account_id, str) and account.account_id.strip():
                candidates.add(account.account_id.strip().lstrip('@').lower())
            return handle in candidates and handle != ""
        except Exception:
            return False

    async def _build_style_context(
        self,
        scraper: TweetScraper,
        browser_manager: BrowserManager,
        account: AccountConfig,
        max_items: int = 10,
    ):
        def _normalize_handle(raw_value):
            if not raw_value:
                return None
            value = str(raw_value).strip()
            if not value:
                return None
            if value.lower().startswith("https://"):
                parts = value.split("x.com/")
                if len(parts) > 1:
                    value = parts[-1]
            value = value.split('?')[0].strip('/').lstrip('@')
            return value.lower() or None

        handle_candidates = []
        if getattr(browser_manager, 'logged_in_handle', None):
            handle_candidates.append(browser_manager.logged_in_handle)
        if account.self_handles:
            handle_candidates.extend([h for h in account.self_handles if h])
        handle_candidates.append(account.account_id)

        normalized_handles = []
        seen_handles = set()
        for raw in handle_candidates:
            normalized = _normalize_handle(raw)
            if normalized and normalized not in seen_handles:
                seen_handles.add(normalized)
                normalized_handles.append(normalized)

        tweets_collected = []
        profile_used = None
        for handle in normalized_handles:
            profile_url = f"https://x.com/{handle}"
            try:
                tweets = await asyncio.to_thread(
                    scraper.scrape_tweets_from_profile,
                    profile_url,
                    max_tweets=max(max_items * 2, 20),
                )
            except Exception as scrape_error:
                logger.error(f"[{account.account_id}] Failed to scrape profile {profile_url} for style context: {scrape_error}", exc_info=True)
                continue
            valid = [t for t in tweets if t and getattr(t, 'text_content', None)]
            if valid:
                tweets_collected = valid
                profile_used = profile_url
                break

        if not tweets_collected:
            logger.warning(f"[{account.account_id}] Unable to gather recent tweets for style context.")
            return "", {}

        seen_ids = set()
        unique_tweets = []
        for tweet in tweets_collected:
            tweet_id = getattr(tweet, 'tweet_id', None)
            if not tweet_id or tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)
            unique_tweets.append(tweet)

        if not unique_tweets:
            return "", {}

        style_context_text, style_memory = build_style_snapshot(
            unique_tweets,
            normalized_handles,
            max_items=max_items,
        )
        if not style_memory:
            return "", {}

        style_memory.update(
            {
                'account_id': account.account_id,
                'profile_url': str(profile_used) if profile_used else None,
            }
        )

        try:
            style_memory_dir = Path(PROJECT_ROOT) / 'data' / 'style_memory'
            self.file_handler.ensure_directory_exists(style_memory_dir)
            style_memory_path = style_memory_dir / f"{account.account_id}.json"
            self.file_handler.write_json(style_memory_path, style_memory)
            logger.info(
                f"[{account.account_id}] Refreshed style memory with {len(style_memory.get('entries', []))} entries."
            )
        except Exception as write_error:
            logger.error(f"[{account.account_id}] Failed to persist style memory: {write_error}", exc_info=True)

        return style_context_text, style_memory

    @staticmethod
    def _score_home_timeline_tweet(tweet: ScrapedTweet) -> float:
        """Generate a simple popularity score combining likes, retweets, replies, and views."""
        likes = tweet.like_count or 0
        retweets = tweet.retweet_count or 0
        replies = tweet.reply_count or 0
        views = tweet.view_count or 0
        return (likes * 2.5) + (retweets * 3.0) + (replies * 1.2) + (views * 0.001)

    async def _run_home_timeline_replies(
        self,
        scraper: TweetScraper,
        publisher: TweetPublisher,
        llm_service: LLMService,
        browser_manager: BrowserManager,
        account: AccountConfig,
        action_config: ActionConfig,
        llm_for_reply: LLMSettings,
        metrics: MetricsRecorder,
    ) -> None:
        replies_per_hour = max(1, action_config.home_timeline_replies_per_hour or 10)
        max_hours = max(1, action_config.home_timeline_max_hours or 3)
        total_cap = replies_per_hour * max_hours
        min_delay = max(10, action_config.min_delay_between_actions_seconds)
        max_delay = max(min_delay, action_config.max_delay_between_actions_seconds)

        session_start = datetime.now(timezone.utc)
        session_end = session_start + timedelta(hours=max_hours)
        current_hour_start = session_start
        replies_sent_total = 0
        replies_this_hour = 0

        logger.info(
            f"[{account.account_id}] Starting home timeline reply session: up to {replies_per_hour} replies/hour, max {max_hours} hours ({total_cap} replies cap)."
        )

        style_context_text = ""
        style_metadata = {}
        style_system_prompt = None
        try:
            style_context_text, style_metadata = await self._build_style_context(scraper, browser_manager, account)
            entries_count = len(style_metadata.get('entries', [])) if style_metadata else 0
            if entries_count:
                media_entry_count = style_metadata.get('media_entry_count', 0)
                logger.info(
                    f"[{account.account_id}] Loaded style context with {entries_count} recent posts (media in {media_entry_count}) from {style_metadata.get('profile_url')}.")
                if metrics:
                    metrics.log_event(
                        'style_memory_refresh',
                        'success',
                        {
                            'entries': entries_count,
                            'media_entries': media_entry_count,
                            'profile_url': style_metadata.get('profile_url'),
                        },
                    )
        except Exception as style_error:
            logger.error(f"[{account.account_id}] Failed to prepare style context: {style_error}", exc_info=True)
            style_context_text = ""
            style_metadata = {}
            if metrics:
                metrics.log_event(
                    'style_memory_refresh',
                    'failure',
                    {
                        'reason': str(style_error)[:200],
                    },
                )

        style_summary = style_metadata.get('style_summary') if style_metadata else None
        style_keywords = style_metadata.get('keyword_signature', []) if style_metadata else []

        media_references = ""
        inline_media_payload: List[Dict[str, Any]] = []
        if style_metadata:
            media_entries = [entry for entry in style_metadata.get('entries', []) if entry.get('media_urls')]
            if media_entries:
                lines = []
                for entry in media_entries[:5]:
                    media_urls = [str(url) for url in entry.get('media_urls') or [] if url]
                    if not media_urls:
                        continue
                    lines.append(
                        "Media reference: " + ", ".join(media_urls)
                    )
                    existing_urls = {
                        str(part['source']['url'])
                        for media in inline_media_payload
                        for part in media.get('parts', [])
                        if part.get('type') == 'media'
                        and isinstance(part.get('source'), dict)
                        and part['source'].get('type') == 'url'
                        and part['source'].get('url')
                    }
                    for media_url in media_urls:
                        media_url_str = str(media_url)
                        if media_url_str in existing_urls:
                            continue
                        inline_media_payload.append(
                            {
                                'role': 'user',
                                'parts': [
                                    {'type': 'text', 'text': f"Reference post media ({entry.get('tweet_id', 'unknown')}):"},
                                    {'type': 'media', 'media_type': 'image', 'source': {'type': 'url', 'url': media_url_str}},
                                ],
                            }
                        )
                        existing_urls.add(media_url_str)
                        if len(inline_media_payload) >= 4:
                            break
                    if len(inline_media_payload) >= 4:
                        break
                if lines:
                    media_references = "\n" + "\n".join(lines)

        style_owner_handle = (
            style_metadata.get('primary_handle')
            if style_metadata else None
        ) or getattr(browser_manager, 'logged_in_handle', None) or account.account_id
        style_owner_handle = str(style_owner_handle).lstrip('@') if style_owner_handle else account.account_id

        base_system_prompt = (
            f"You are @{style_owner_handle}. Reply directly to the provided tweet. "
            f"Keep responses under 270 characters, natural, and explicitly about the tweet's content."
        )

        template = (
            account.action_config.style_prompt_template
            if account.action_config and account.action_config.style_prompt_template
            else None
        )
        if template:
            context_for_template = style_summary or style_context_text or "No recent style context available."
            try:
                style_system_prompt = template.format(
                    handle=style_owner_handle,
                    style_context=context_for_template,
                    media_references=media_references,
                    account_id=account.account_id,
                )
            except Exception as template_error:
                logger.error(
                    f"[{account.account_id}] Failed to apply custom style_prompt_template: {template_error}",
                    exc_info=True,
                )
                style_system_prompt = base_system_prompt
        else:
            style_system_prompt = base_system_prompt

        per_reply_target_seconds = 3600.0 / float(replies_per_hour)
        spacing_min_seconds = max(float(min_delay), per_reply_target_seconds)
        spacing_max_candidate = float(max_delay)
        if spacing_max_candidate < spacing_min_seconds:
            spacing_max_seconds = spacing_min_seconds + max(30.0, spacing_min_seconds * 0.15)
        else:
            spacing_max_seconds = spacing_max_candidate
        if spacing_max_seconds - spacing_min_seconds < 1.0:
            spacing_max_seconds = spacing_min_seconds + max(5.0, spacing_min_seconds * 0.05)

        next_reply_earliest = datetime.now(timezone.utc)
        logger.info(
            f"[{account.account_id}] Pacing replies with at least {spacing_min_seconds:.0f}s (~{spacing_min_seconds / 60.0:.1f} min) between attempts."
        )

        while replies_sent_total < total_cap:
            now = datetime.now(timezone.utc)
            if now >= session_end:
                logger.info(f"[{account.account_id}] Home timeline session reached {max_hours} hour limit, stopping.")
                break

            if (now - current_hour_start).total_seconds() >= 3600:
                logger.debug(f"[{account.account_id}] Advancing to next hourly window for home timeline replies.")
                current_hour_start = now
                replies_this_hour = 0

            if replies_this_hour >= replies_per_hour:
                next_hour_time = current_hour_start + timedelta(hours=1)
                sleep_seconds = (next_hour_time - now).total_seconds()
                remaining_session = (session_end - now).total_seconds()
                if remaining_session <= 0:
                    logger.info(f"[{account.account_id}] Session time exhausted while waiting for next hour.")
                    break
                sleep_seconds = max(0.0, min(sleep_seconds, remaining_session))
                if sleep_seconds <= 0:
                    current_hour_start = datetime.now(timezone.utc)
                    replies_this_hour = 0
                    continue
                minutes = sleep_seconds / 60.0
                logger.info(
                    f"[{account.account_id}] Reached hourly cap ({replies_per_hour}). Cooling down for {minutes:.1f} minutes before resuming."
                )
                await asyncio.sleep(sleep_seconds)
                next_reply_earliest = max(next_reply_earliest, datetime.now(timezone.utc))
                current_hour_start = datetime.now(timezone.utc)
                replies_this_hour = 0
                continue

            batch_limit = max(40, replies_per_hour * 4)
            tweets = await asyncio.to_thread(
                scraper.scrape_home_timeline,
                batch_limit,
            )

            if not tweets:
                logger.info(f"[{account.account_id}] No tweets retrieved from home timeline. Ending session early.")
                break

            scored_candidates = sorted(
                tweets,
                key=self._score_home_timeline_tweet,
                reverse=True,
            )

            made_reply_this_batch = False

            for candidate in scored_candidates:
                if replies_this_hour >= replies_per_hour or replies_sent_total >= total_cap:
                    break

                if not candidate.tweet_id:
                    continue

                if candidate.user_handle and self._is_own_tweet(candidate.user_handle, account, browser_manager):
                    continue

                action_key = f"home_reply_{account.account_id}_{candidate.tweet_id}"
                if action_key in self.processed_action_keys:
                    continue

                tweet_inline_media = []
                if candidate.embedded_media_urls:
                    for media_url in candidate.embedded_media_urls[:4]:  # Limit to 4 media items
                        tweet_inline_media.append(
                            {
                                'role': 'user',
                                'parts': [
                                    {'type': 'text', 'text': "Media from the tweet you're replying to:"},
                                    {'type': 'media', 'media_type': 'image', 'source': {'type': 'url', 'url': str(media_url)}},
                                ],
                            }
                        )

                use_style_profile = should_apply_style_profile(candidate, style_keywords)
                system_prompt_for_reply = style_system_prompt if use_style_profile else base_system_prompt
                summary_for_reply = style_summary if use_style_profile else None

                try:
                    generated_reply_text, guard_metadata = await generate_guarded_reply(
                        llm_service=llm_service,
                        tweet=candidate,
                        llm_settings=llm_for_reply,
                        system_prompt=system_prompt_for_reply,
                        style_summary=summary_for_reply,
                        persona_handle=style_owner_handle,
                        inline_media=tweet_inline_media,
                        banned_terms=None,
                        retry_limit=2,
                    )
                except Exception as llm_error:
                    logger.error(f"[{account.account_id}] LLM failed to generate reply for {candidate.tweet_id}: {llm_error}")
                    metrics.increment('errors')
                    metrics.log_event(
                        'home_timeline_reply',
                        'failure',
                        {'tweet_id': candidate.tweet_id, 'reason': 'llm_error'},
                    )
                    continue

                if not generated_reply_text:
                    logger.debug(
                        f"[{account.account_id}] Guardrails blocked reply for tweet {candidate.tweet_id}: {guard_metadata.get('relevance_reason')}"
                    )
                    metrics.log_event(
                        'home_timeline_reply',
                        'skipped',
                        {
                            'tweet_id': candidate.tweet_id,
                            'reason': guard_metadata.get('relevance_reason'),
                            'attempts': guard_metadata.get('attempts'),
                        },
                    )
                    continue

                generated_reply_text = generated_reply_text[:270].rstrip()
                if not generated_reply_text:
                    logger.debug(
                        f"[{account.account_id}] Generated reply empty after trimming for tweet {candidate.tweet_id}. Skipping."
                    )
                    metrics.log_event(
                        'home_timeline_reply',
                        'skipped',
                        {
                            'tweet_id': candidate.tweet_id,
                            'reason': 'empty_after_trim',
                            'attempts': guard_metadata.get('attempts'),
                        },
                    )
                    continue

                now_for_pacing = datetime.now(timezone.utc)
                if now_for_pacing < next_reply_earliest:
                    wait_seconds = (next_reply_earliest - now_for_pacing).total_seconds()
                    if wait_seconds > 0:
                        logger.info(
                            f"[{account.account_id}] Waiting {wait_seconds / 60.0:.1f} minutes before next reply to honor pacing."
                        )
                        await asyncio.sleep(wait_seconds)

                logger.info(
                    f"[{account.account_id}] Attempting home timeline reply {replies_sent_total + 1}/{total_cap} "
                    f"(hour slot {replies_this_hour + 1}/{replies_per_hour}) on tweet {candidate.tweet_id}."
                )

                success = await publisher.reply_to_tweet(candidate, generated_reply_text)
                attempt_completed_at = datetime.now(timezone.utc)
                next_delay = random.uniform(spacing_min_seconds, spacing_max_seconds)
                next_reply_earliest = attempt_completed_at + timedelta(seconds=next_delay)
                logger.debug(
                    f"[{account.account_id}] Scheduled next reply attempt no sooner than {next_reply_earliest.isoformat()} (delay {next_delay:.0f}s)."
                )
                if success:
                    score = self._score_home_timeline_tweet(candidate)
                    replies_sent_total += 1
                    replies_this_hour += 1
                    metrics.increment('replies')
                    metrics.log_event(
                        'home_timeline_reply',
                        'success',
                        {
                            'tweet_id': candidate.tweet_id,
                            'score': score,
                            'likes': candidate.like_count,
                            'retweets': candidate.retweet_count,
                            'views': candidate.view_count,
                            'media_in_style_context': bool(media_references.strip()),
                            'style_applied': use_style_profile,
                            'guard_attempts': guard_metadata.get('attempts'),
                            'flagged_terms': guard_metadata.get('flagged_terms'),
                        },
                    )
                    log_index = f"{replies_sent_total}/{total_cap}"
                    logger.info(
                        f"[{account.account_id}] Home timeline reply {log_index} complete for tweet {candidate.tweet_id} (score {score:.2f})."
                    )
                    self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                    self.processed_action_keys.add(action_key)
                    made_reply_this_batch = True
                    break
                else:
                    metrics.increment('errors')
                    metrics.log_event(
                        'home_timeline_reply',
                        'failure',
                        {'tweet_id': candidate.tweet_id, 'reason': 'selenium_failure'},
                    )
                    logger.error(f"[{account.account_id}] Failed to post reply to home timeline tweet {candidate.tweet_id}.")

            if not made_reply_this_batch:
                logger.info(f"[{account.account_id}] No suitable home timeline tweets produced replies this batch. Ending session.")
                break

    async def _decide_competitor_action(self, analyzer: TweetAnalyzer, tweet: ScrapedTweet, account: AccountConfig) -> str:
        """Return one of: 'repost', 'retweet', 'quote_tweet', 'like' based on relevance and sentiment, honoring per-account overrides and thresholds."""
        acc_ac = account.action_config
        decision_enabled = (acc_ac.enable_engagement_decision if (acc_ac and acc_ac.enable_engagement_decision is not None)
                            else self.engagement_decision_cfg.get('enabled', False))
        use_sentiment = (acc_ac.use_sentiment_in_decision if (acc_ac and acc_ac.use_sentiment_in_decision is not None)
                         else self.engagement_decision_cfg.get('use_sentiment', True))
        # Thresholds: per-account overrides > global cfg > defaults
        ed_thr = (self.engagement_decision_cfg.get('thresholds') or {}) if isinstance(self.engagement_decision_cfg, dict) else {}
        quote_min = (acc_ac.decision_quote_min if (acc_ac and acc_ac.decision_quote_min is not None) else float(ed_thr.get('quote_min', 0.75)))
        retweet_min = (acc_ac.decision_retweet_min if (acc_ac and acc_ac.decision_retweet_min is not None) else float(ed_thr.get('retweet_min', 0.5)))
        repost_min = (acc_ac.decision_repost_min if (acc_ac and acc_ac.decision_repost_min is not None) else float(ed_thr.get('repost_min', 0.35)))
        if not decision_enabled:
            return (acc_ac.competitor_post_interaction_type if acc_ac else 'repost')
        # Try structured analysis first
        structured = await analyzer.analyze_tweet_structured(tweet, keywords=account.target_keywords)
        if structured and isinstance(structured, dict) and 'recommended_action' in structured:
            rel = float(structured.get('relevance', 0.0) or 0.0)
            sentiment = str(structured.get('sentiment', 'neutral') or 'neutral').lower()
            rec = str(structured.get('recommended_action')).lower()
            # Apply minimal guardrails based on thresholds
            if rel < repost_min:
                return 'like'
            if rec in ('quote_tweet', 'retweet', 'repost', 'like'):
                return rec
        # Fallback: Compute relevance and optionally sentiment
        rel = await analyzer.score_relevance(tweet, keywords=account.target_keywords)
        sentiment = 'neutral'
        if use_sentiment:
            try:
                sentiment = await analyzer.classify_sentiment(tweet)
            except Exception:
                sentiment = 'neutral'
        # Simple heuristic mapping
        if rel >= quote_min and sentiment in ('positive', 'neutral'):
            return 'quote_tweet'
        if rel >= retweet_min and sentiment in ('positive', 'neutral'):
            return 'retweet'
        if rel >= repost_min:
            return 'repost'
        return 'like'

    async def _process_account(self, account_dict: dict):
        """Processes tasks for a single Twitter account."""
        
        # Normalize legacy override keys to current AccountConfig fields
        def _normalize_account_config(d: dict) -> dict:
            normalized = dict(d)  # shallow copy
            # Map legacy override fields if the new ones are missing
            if 'target_keywords' not in normalized and 'target_keywords_override' in normalized:
                normalized['target_keywords'] = normalized.get('target_keywords_override')
            if 'competitor_profiles' not in normalized and 'competitor_profiles_override' in normalized:
                normalized['competitor_profiles'] = normalized.get('competitor_profiles_override')
            if 'news_sites' not in normalized and 'news_sites_override' in normalized:
                normalized['news_sites'] = normalized.get('news_sites_override')
            if 'research_paper_sites' not in normalized and 'research_paper_sites_override' in normalized:
                normalized['research_paper_sites'] = normalized.get('research_paper_sites_override')
            if 'action_config' not in normalized and 'action_config_override' in normalized:
                normalized['action_config'] = normalized.get('action_config_override')
            # Keep llm_settings_override as-is (same field name in model)
            return normalized

        account_dict = _normalize_account_config(account_dict)

        # Create AccountConfig Pydantic model from the dictionary
        try:
            # A simple way to map, assuming keys in dict match model fields or are handled by default values
            # account_config_data = {k: account_dict.get(k) for k in AccountConfig.model_fields.keys() if account_dict.get(k) is not None}
            # if 'cookies' in account_dict and isinstance(account_dict['cookies'], str): # If 'cookies' is a file path string
            #     account_config_data['cookie_file_path'] = account_dict['cookies']
            #     if 'cookies' in account_config_data: del account_config_data['cookies'] # Avoid conflict if model expects List[AccountCookie]
            
            # Use Pydantic's parse_obj method for robust parsing from dict
            account = AccountConfig.model_validate(account_dict) # Replaced AccountConfig(**account_dict) for better validation
            
        except Exception as e: # Catch Pydantic ValidationError specifically if needed
            logger.error(f"Failed to parse account configuration for {account_dict.get('account_id', 'UnknownAccount')}: {e}. Skipping account.")
            return

        if not account.is_active:
            logger.info(f"Account {account.account_id} is inactive. Skipping.")
            return

        logger.info(f"--- Starting processing for account: {account.account_id} ---")
        
        browser_manager = None
        metrics = None
        try:
            browser_manager = BrowserManager(account_config=account_dict) # Pass original dict for cookie path handling
            llm_service = LLMService(config_loader=self.config_loader)
            
            # Initialize feature modules with the current account's context
            scraper = TweetScraper(browser_manager, account_id=account.account_id)
            publisher = TweetPublisher(browser_manager, llm_service, account) # Publisher needs AccountConfig model
            engagement = TweetEngagement(browser_manager, account) # Engagement needs AccountConfig model
            metrics = MetricsRecorder(account_id=account.account_id, config_loader=self.config_loader)
            metrics.mark_run_start()

            # --- Define actions based on global and account-specific settings ---
            automation_settings = self.global_settings.get('twitter_automation', {}) # Global settings for twitter_automation
            
            # Determine current ActionConfig: account's action_config > global default action_config
            global_action_config_dict = automation_settings.get('action_config', {}) # Global default action_config
            current_action_config = account.action_config or ActionConfig(**global_action_config_dict) # account.action_config is now the primary source if it exists

            # Initialize TweetAnalyzer
            analyzer = TweetAnalyzer(llm_service, account_config=account)

            # Determine LLM settings for different actions:
            # Priority: Account's general LLM override -> Action-specific LLM settings from current_action_config
            llm_for_post = account.llm_settings_override or current_action_config.llm_settings_for_post
            llm_for_reply = account.llm_settings_override or current_action_config.llm_settings_for_reply
            llm_for_thread_analysis = account.llm_settings_override or current_action_config.llm_settings_for_thread_analysis
            
            # Determine automation mode for inbound content
            competitor_profiles_for_account = account.competitor_profiles
            home_timeline_enabled = (
                current_action_config.enable_home_timeline_replies
                if current_action_config.enable_home_timeline_replies is not None
                else False
            )

            if home_timeline_enabled:
                await self._run_home_timeline_replies(
                    scraper,
                    publisher,
                    llm_service,
                    browser_manager,
                    account,
                    current_action_config,
                    llm_for_reply,
                    metrics,
                )
                logger.info(
                    f"[{account.account_id}] Home timeline only mode active; skipping all other automation tasks."
                )
                return

            # Action 1: Scrape competitor profiles and generate/post new tweets (only when allowed)
            # Content sources are now directly from the account config, defaulting to empty lists if not provided.
            
            if (
                current_action_config.enable_competitor_reposts
                and competitor_profiles_for_account
                and not home_timeline_enabled
            ):
                logger.info(f"[{account.account_id}] Starting competitor profile scraping and posting using {len(competitor_profiles_for_account)} profiles.")
                for profile_url in competitor_profiles_for_account:
                    logger.info(f"[{account.account_id}] Scraping profile: {str(profile_url)}")
                    
                    tweets_from_profile = await asyncio.to_thread(
                        scraper.scrape_tweets_from_profile, 
                        str(profile_url), 
                        max_tweets=current_action_config.max_posts_per_competitor_run * 3
                    )
                    
                    posts_made_this_profile = 0
                    for scraped_tweet in tweets_from_profile:
                        if posts_made_this_profile >= current_action_config.max_posts_per_competitor_run:
                            break
                        # Optional relevance filter (settings-driven)
                        try:
                            acc_ac = account.action_config
                            enable_rel = (acc_ac.enable_relevance_filter_competitor_reposts if (acc_ac and acc_ac.enable_relevance_filter_competitor_reposts is not None)
                                          else self.analysis_config.get('enable_relevance_filter', {}).get('competitor_reposts', True))
                            thr = (acc_ac.relevance_threshold_competitor_reposts if (acc_ac and acc_ac.relevance_threshold_competitor_reposts is not None)
                                   else float(self.analysis_config.get('thresholds', {}).get('competitor_reposts_min', 0.35)))
                            if enable_rel:
                                rel_score = await analyzer.score_relevance(scraped_tweet, keywords=account.target_keywords)
                                if rel_score < thr:
                                    logger.debug(f"[{account.account_id}] Skipping tweet {scraped_tweet.tweet_id} (rel {rel_score:.2f} < {thr}).")
                                    continue
                        except Exception:
                            pass
                        
                        if current_action_config.repost_only_tweets_with_media and not scraped_tweet.embedded_media_urls:
                            logger.debug(f"[{account.account_id}] Skipping tweet {scraped_tweet.tweet_id} (no media).")
                            continue
                        if (scraped_tweet.like_count or 0) < current_action_config.min_likes_for_repost_candidate:
                            logger.debug(f"[{account.account_id}] Skipping tweet {scraped_tweet.tweet_id} (likes {scraped_tweet.like_count} < min).")
                            continue
                        if (scraped_tweet.retweet_count or 0) < current_action_config.min_retweets_for_repost_candidate:
                            logger.debug(f"[{account.account_id}] Skipping tweet {scraped_tweet.tweet_id} (retweets {scraped_tweet.retweet_count} < min).")
                            continue

                        interaction_type = await self._decide_competitor_action(analyzer, scraped_tweet, account)
                        action_key = f"{interaction_type}_{account.account_id}_{scraped_tweet.tweet_id}"
                            
                        if action_key in self.processed_action_keys:
                            logger.info(f"[{account.account_id}] Action '{action_key}' already processed. Skipping.")
                            continue

                        if scraped_tweet.is_thread_candidate and current_action_config.enable_thread_analysis:
                            logger.info(f"[{account.account_id}] Analyzing thread candidacy for tweet {scraped_tweet.tweet_id}...")
                            is_confirmed = await analyzer.check_if_thread_with_llm(scraped_tweet, custom_llm_settings=llm_for_thread_analysis)
                            scraped_tweet.is_confirmed_thread = is_confirmed
                            logger.info(f"[{account.account_id}] Thread analysis result for {scraped_tweet.tweet_id}: {is_confirmed}")

                        interaction_success = False

                        if interaction_type == "like":
                            logger.info(f"[{account.account_id}] Decided to like tweet {scraped_tweet.tweet_id}.")
                            interaction_success = await engagement.like_tweet(tweet_id=scraped_tweet.tweet_id, tweet_url=str(scraped_tweet.tweet_url) if scraped_tweet.tweet_url else None)
                            if interaction_success:
                                metrics.increment('likes')
                                metrics.log_event('like', 'success', {'source': 'competitor', 'tweet_id': scraped_tweet.tweet_id})
                            else:
                                metrics.increment('errors')
                                metrics.log_event('like', 'failure', {'source': 'competitor', 'tweet_id': scraped_tweet.tweet_id})
                        elif interaction_type == "repost":
                            prompt = f"Rewrite this tweet in an engaging way: '{scraped_tweet.text_content}' by {scraped_tweet.user_handle or 'a user'}."
                            if scraped_tweet.is_confirmed_thread:
                                prompt = f"This tweet is part of a thread. Rewrite its essence engagingly: '{scraped_tweet.text_content}' by {scraped_tweet.user_handle or 'a user'}."
                            new_tweet_content = TweetContent(text=prompt)
                            logger.info(f"[{account.account_id}] Generating and posting new tweet based on {scraped_tweet.tweet_id}")
                            interaction_success = await publisher.post_new_tweet(new_tweet_content, llm_settings=llm_for_post)
                            metrics.log_event('post', 'success' if interaction_success else 'failure', {'source': 'competitor', 'tweet_id': scraped_tweet.tweet_id})
                            if interaction_success:
                                metrics.increment('posts')
                        
                        elif interaction_type == "retweet":
                            logger.info(f"[{account.account_id}] Attempting to retweet {scraped_tweet.tweet_id}")
                            interaction_success = await publisher.retweet_tweet(scraped_tweet)
                            metrics.log_event('retweet', 'success' if interaction_success else 'failure', {'tweet_id': scraped_tweet.tweet_id})
                            if interaction_success:
                                metrics.increment('retweets')
                        
                        elif interaction_type == "quote_tweet":
                            quote_prompt_template = current_action_config.prompt_for_quote_tweet_from_competitor
                            quote_prompt = quote_prompt_template.format(
                                user_handle=(scraped_tweet.user_handle or "a user"), 
                                tweet_text=scraped_tweet.text_content
                            )
                            logger.info(f"[{account.account_id}] Attempting to quote tweet {scraped_tweet.tweet_id} with generated text.")
                            # LLM settings for quote tweets could be distinct if added to ActionConfig, for now using llm_for_post
                            interaction_success = await publisher.retweet_tweet(scraped_tweet, 
                                                                                quote_text_prompt_or_direct=quote_prompt, 
                                                                                llm_settings_for_quote=llm_for_post)
                            metrics.log_event('quote_tweet', 'success' if interaction_success else 'failure', {'tweet_id': scraped_tweet.tweet_id})
                            if interaction_success:
                                metrics.increment('quote_tweets')
                        else:
                            logger.warning(f"[{account.account_id}] Unknown competitor_post_interaction_type: {interaction_type}")
                            continue

                        if interaction_success:
                            self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                            self.processed_action_keys.add(action_key) # Add to in-memory set for current run
                            if interaction_type != 'like':
                                posts_made_this_profile += 1
                            await asyncio.sleep(random.uniform(current_action_config.min_delay_between_actions_seconds, current_action_config.max_delay_between_actions_seconds))
                        else:
                            logger.error(f"[{account.account_id}] Failed to {interaction_type} based on tweet {scraped_tweet.tweet_id}")
                            metrics.increment('errors')

            elif current_action_config.enable_competitor_reposts and not home_timeline_enabled:
                logger.info(f"[{account.account_id}] Competitor reposts enabled, but no competitor profiles configured for this account.")

            # Action 1.5: Engage with posts inside a configured Community
            if (
                current_action_config.enable_community_engagement
                and account.community_id
            ):
                try:
                    community_url = f"https://x.com/i/communities/{account.community_id}"
                    logger.info(f"[{account.account_id}] Scraping community timeline: {community_url}")
                    # Scrape more than we plan to act on so we can filter
                    to_scrape = max(10, current_action_config.max_community_engagements_per_run * 4)
                    community_tweets = await asyncio.to_thread(
                        scraper.scrape_tweets_from_url,
                        community_url,
                        "community",
                        to_scrape,
                    )

                    total_community_actions = 0
                    replies_made_in_community = 0

                    for ct in community_tweets:
                        if total_community_actions >= current_action_config.max_community_engagements_per_run:
                            break

                        # Avoid re-processing the same tweet for the same action
                        # We'll create an action key per decided action below.

                        # Decide how to engage (reuse competitor decision logic + thresholds)
                        # Skip own posts entirely in the community
                        if ct.user_handle and self._is_own_tweet(ct.user_handle, account, browser_manager):
                            logger.info(f"[{account.account_id}] Skipping own community post {ct.tweet_id} ({ct.user_handle}).")
                            try:
                                skip_key = f"skip_own_{account.account_id}_{ct.tweet_id}"
                                self.file_handler.save_processed_action_key(skip_key, timestamp=datetime.now().isoformat())
                                self.processed_action_keys.add(skip_key)
                            except Exception:
                                pass
                            continue

                        decided_action = await self._decide_competitor_action(analyzer, ct, account)
                        # Map 'repost' to 'retweet' for community (we do not synthesize new standalone posts here)
                        if decided_action == 'repost' or decided_action == 'quote_tweet':
                            # For community, collapse to a simple retweet action
                            decided_action = 'retweet'

                        interaction_success = False

                        if decided_action == 'like' and current_action_config.enable_community_likes:
                            action_key = f"community_like_{account.account_id}_{ct.tweet_id}"
                            if action_key in self.processed_action_keys:
                                continue
                            logger.info(f"[{account.account_id}] Liking community post {ct.tweet_id}")
                            interaction_success = await engagement.like_tweet(ct.tweet_id, str(ct.tweet_url) if ct.tweet_url else None)
                            metrics.log_event('community_like', 'success' if interaction_success else 'failure', {'tweet_id': ct.tweet_id})
                            if interaction_success:
                                metrics.increment('likes')
                                self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                                self.processed_action_keys.add(action_key)
                                total_community_actions += 1

                        elif decided_action == "retweet" and current_action_config.enable_community_retweets:
                            action_key = f"community_{decided_action}_{account.account_id}_{ct.tweet_id}"
                            if action_key in self.processed_action_keys:
                                continue
                            logger.info(f"[{account.account_id}] Retweeting community post {ct.tweet_id}")
                            interaction_success = await publisher.retweet_tweet(ct, quote_text_prompt_or_direct=None)
                            metrics.log_event('community_retweet', 'success' if interaction_success else 'failure', {'tweet_id': ct.tweet_id})
                            if interaction_success:
                                metrics.increment('retweets')

                            if interaction_success:
                                self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                                self.processed_action_keys.add(action_key)
                                total_community_actions += 1

                        # Optional: Replies to community posts (independent gate and cap)
                        if (
                            current_action_config.enable_community_replies
                            and replies_made_in_community < current_action_config.max_community_replies_per_run
                        ):
                            reply_key = f"community_reply_{account.account_id}_{ct.tweet_id}"
                            if reply_key in self.processed_action_keys:
                                # Already replied to this post in past runs
                                pass
                            else:
                                # Respect recency window if configured
                                try:
                                    hours_limit = current_action_config.community_reply_only_recent_tweets_hours
                                    if hours_limit and ct.created_at:
                                        now_utc = datetime.now(timezone.utc)
                                        age_hours = (now_utc - ct.created_at).total_seconds() / 3600
                                        if age_hours > hours_limit:
                                            logger.debug(f"[{account.account_id}] Skipping community reply for {ct.tweet_id}, age {age_hours:.1f}h > {hours_limit}h")
                                            raise Exception("skip_reply_due_to_age")
                                except Exception:
                                    # Skip on explicit age failure; do not treat as error
                                    pass
                                else:
                                    # Do not reply to own posts
                                    if ct.user_handle and self._is_own_tweet(ct.user_handle, account, browser_manager):
                                        logger.info(f"[{account.account_id}] Skipping own community post {ct.tweet_id} for reply.")
                                        try:
                                            skip_key = f"skip_own_{account.account_id}_{ct.tweet_id}"
                                            self.file_handler.save_processed_action_key(skip_key, timestamp=datetime.now().isoformat())
                                            self.processed_action_keys.add(skip_key)
                                        except Exception:
                                            pass
                                        continue
                                    # Build context-aware reply prompt with proper media handling
                                    tweet_media_context = ""
                                    tweet_inline_media = []
                                    if ct.embedded_media_urls:
                                        media_count = len(ct.embedded_media_urls)
                                        tweet_media_context = f"\n[This tweet contains {media_count} media item(s)]"
                                        for media_url in ct.embedded_media_urls[:4]:
                                            tweet_inline_media.append({
                                                'role': 'user',
                                                'parts': [
                                                    {'type': 'text', 'text': f"Media from the community tweet:"},
                                                    {'type': 'media', 'media_type': 'image', 'source': {'type': 'url', 'url': str(media_url)}},
                                                ],
                                            })

                                    reply_prompt = (
                                        f"TASK: Write a concise, natural reply under 270 characters that is DIRECTLY RELEVANT to this community post.{tweet_media_context}\n\n"
                                        f"Post by @{ct.user_handle or 'user'}:\n\"{ct.text_content}\"\n\n"
                                        f"Your reply (stay on-topic, avoid hashtags/links/emojis):"
                                    )
                                    logger.info(f"[{account.account_id}] Replying to community post {ct.tweet_id}")
                                    generated_reply_text = await llm_service.generate_text(
                                        prompt=reply_prompt,
                                        service_preference=llm_for_reply.service_preference,
                                        model_name=llm_for_reply.model_name_override,
                                        max_tokens=llm_for_reply.max_tokens,
                                        temperature=llm_for_reply.temperature,
                                        inline_media=tweet_inline_media,
                                    )
                                    generated_reply_text = (generated_reply_text or "")[:270].rstrip()
                                    if generated_reply_text:
                                        reply_success = await publisher.reply_to_tweet(ct, generated_reply_text)
                                        metrics.log_event('community_reply', 'success' if reply_success else 'failure', {'tweet_id': ct.tweet_id})
                                        if reply_success:
                                            metrics.increment('replies')
                                            self.file_handler.save_processed_action_key(reply_key, timestamp=datetime.now().isoformat())
                                            self.processed_action_keys.add(reply_key)
                                            replies_made_in_community += 1
                                            total_community_actions += 1

                        # Backoff between actions to be human-like
                        if total_community_actions >= current_action_config.max_community_engagements_per_run:
                            break
                        await asyncio.sleep(random.uniform(current_action_config.min_delay_between_actions_seconds, current_action_config.max_delay_between_actions_seconds))

                except Exception as e:
                    logger.error(f"[{account.account_id}] Failed during community engagement: {e}", exc_info=True)
                    metrics.increment('errors')

            # Action 2: Scrape keywords and reply
            target_keywords_for_account = account.target_keywords
            if current_action_config.enable_keyword_replies and target_keywords_for_account:
                logger.info(f"[{account.account_id}] Starting keyword scraping and replying for {len(target_keywords_for_account)} keywords.")
                for keyword in target_keywords_for_account:
                    logger.info(f"[{account.account_id}] Processing keyword for replies: '{keyword}'")
                    # Scrape tweets for the keyword
                    tweets_for_keyword = await asyncio.to_thread(
                        scraper.scrape_tweets_by_keyword,
                        keyword,
                        max_tweets=current_action_config.max_replies_per_keyword_run * 2 # Get more to filter
                    )
                    
                    replies_made_this_keyword = 0
                    for scraped_tweet_to_reply in tweets_for_keyword:
                        if replies_made_this_keyword >= current_action_config.max_replies_per_keyword_run:
                            break

                        action_key = f"reply_{account.account_id}_{scraped_tweet_to_reply.tweet_id}"
                        if action_key in self.processed_action_keys:
                            logger.info(f"[{account.account_id}] Already replied or processed tweet {scraped_tweet_to_reply.tweet_id}. Skipping.")
                            continue
                        
                        if current_action_config.avoid_replying_to_own_tweets and scraped_tweet_to_reply.user_handle and self._is_own_tweet(scraped_tweet_to_reply.user_handle, account, browser_manager):
                            logger.info(f"[{account.account_id}] Skipping own tweet {scraped_tweet_to_reply.tweet_id} for reply.")
                            continue

                        if current_action_config.reply_only_to_recent_tweets_hours and scraped_tweet_to_reply.created_at:
                            now_utc = datetime.now(timezone.utc)
                            tweet_age_hours = (now_utc - scraped_tweet_to_reply.created_at).total_seconds() / 3600
                            if tweet_age_hours > current_action_config.reply_only_to_recent_tweets_hours:
                                logger.info(f"[{account.account_id}] Skipping old tweet {scraped_tweet_to_reply.tweet_id} (age: {tweet_age_hours:.1f}h > limit: {current_action_config.reply_only_to_recent_tweets_hours}h).")
                                continue
                        
                        # Thread Analysis for context before replying (optional, could make reply more relevant)
                        if scraped_tweet_to_reply.is_thread_candidate and current_action_config.enable_thread_analysis:
                            logger.info(f"[{account.account_id}] Analyzing thread candidacy for reply target tweet {scraped_tweet_to_reply.tweet_id}...")
                            is_confirmed = await analyzer.check_if_thread_with_llm(scraped_tweet_to_reply, custom_llm_settings=llm_for_thread_analysis)
                            scraped_tweet_to_reply.is_confirmed_thread = is_confirmed
                            logger.info(f"[{account.account_id}] Thread analysis for reply target {scraped_tweet_to_reply.tweet_id}: {is_confirmed}")

                        # Build context-aware reply prompt with proper media handling
                        tweet_media_context = ""
                        tweet_inline_media = []
                        if scraped_tweet_to_reply.embedded_media_urls:
                            media_count = len(scraped_tweet_to_reply.embedded_media_urls)
                            tweet_media_context = f"\n[This tweet contains {media_count} media item(s)]"
                            for media_url in scraped_tweet_to_reply.embedded_media_urls[:4]:
                                tweet_inline_media.append({
                                    'role': 'user',
                                    'parts': [
                                        {'type': 'text', 'text': f"Media from the tweet you're replying to:"},
                                        {'type': 'media', 'media_type': 'image', 'source': {'type': 'url', 'url': str(media_url)}},
                                    ],
                                })

                        reply_prompt_context = (
                            "This tweet is part of a thread." if scraped_tweet_to_reply.is_confirmed_thread else "This is a standalone tweet."
                        )
                        reply_prompt = (
                            f"TASK: Write a concise, natural reply under 270 characters that is DIRECTLY RELEVANT to this tweet. "
                            f"{reply_prompt_context}{tweet_media_context}\n\n"
                            f"Tweet by @{scraped_tweet_to_reply.user_handle or 'user'}:\n"
                            f"\"{scraped_tweet_to_reply.text_content}\"\n\n"
                            f"Your reply (stay on-topic, avoid hashtags/links/emojis):"
                        )
                        
                        logger.info(f"[{account.account_id}] Generating reply for tweet {scraped_tweet_to_reply.tweet_id}...")
                        generated_reply_text = await llm_service.generate_text(
                            prompt=reply_prompt,
                            service_preference=llm_for_reply.service_preference,
                            model_name=llm_for_reply.model_name_override,
                            max_tokens=llm_for_reply.max_tokens,
                            temperature=llm_for_reply.temperature,
                            inline_media=tweet_inline_media,
                        )

                        if not generated_reply_text:
                            logger.error(f"[{account.account_id}] Failed to generate reply text for tweet {scraped_tweet_to_reply.tweet_id}. Skipping.")
                            continue
                        # Hard-cap reply length to 270 characters
                        generated_reply_text = (generated_reply_text or "")[:270].rstrip()
                        
                        # Optional relevance filter for keyword replies
                        try:
                            acc_ac = account.action_config
                            enable_rel_reply = (acc_ac.enable_relevance_filter_keyword_replies if (acc_ac and acc_ac.enable_relevance_filter_keyword_replies is not None)
                                                else self.analysis_config.get('enable_relevance_filter', {}).get('keyword_replies', False))
                            thr_reply = (acc_ac.relevance_threshold_keyword_replies if (acc_ac and acc_ac.relevance_threshold_keyword_replies is not None)
                                         else float(self.analysis_config.get('thresholds', {}).get('keyword_replies_min', 0.35)))
                            if enable_rel_reply:
                                rel_reply = await analyzer.score_relevance(scraped_tweet_to_reply, keywords=account.target_keywords)
                                if rel_reply < thr_reply:
                                    logger.debug(f"[{account.account_id}] Skipping reply to {scraped_tweet_to_reply.tweet_id} (rel {rel_reply:.2f} < {thr_reply}).")
                                    continue
                        except Exception:
                            pass

                        logger.info(f"[{account.account_id}] Attempting to post reply to tweet {scraped_tweet_to_reply.tweet_id}...")
                        reply_success = await publisher.reply_to_tweet(scraped_tweet_to_reply, generated_reply_text)
                        metrics.log_event('reply', 'success' if reply_success else 'failure', {'tweet_id': scraped_tweet_to_reply.tweet_id})
                        if reply_success:
                            metrics.increment('replies')
                        else:
                            metrics.increment('errors')

                        if reply_success:
                            self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                            self.processed_action_keys.add(action_key)
                            replies_made_this_keyword += 1
                            await asyncio.sleep(random.uniform(current_action_config.min_delay_between_actions_seconds, current_action_config.max_delay_between_actions_seconds))
                        else:
                            logger.error(f"[{account.account_id}] Failed to post reply to tweet {scraped_tweet_to_reply.tweet_id}.")
                            # Optionally, add to a temporary blocklist for this session to avoid retrying immediately
                    logger.info(f"[{account.account_id}] Finished processing keyword '{keyword}' for replies.")
            elif current_action_config.enable_keyword_replies:
                logger.info(f"[{account.account_id}] Keyword replies enabled, but no target keywords configured for this account.")

            # Action 2b: Retweet tweets from keywords
            if getattr(current_action_config, 'enable_keyword_retweets', False) and target_keywords_for_account:
                logger.info(f"[{account.account_id}] Starting keyword-based retweets for {len(target_keywords_for_account)} keywords.")
                for keyword in target_keywords_for_account:
                    logger.info(f"[{account.account_id}] Processing keyword for retweets: '{keyword}'")
                    tweets_for_keyword = await asyncio.to_thread(
                        scraper.scrape_tweets_by_keyword,
                        keyword,
                        max_tweets=max(5, current_action_config.max_retweets_per_keyword_run * 3)
                    )
                    retweets_made = 0
                    for tweet_candidate in tweets_for_keyword:
                        if retweets_made >= current_action_config.max_retweets_per_keyword_run:
                            break
                        # Optional relevance filter: reuse likes filter settings if available
                        try:
                            acc_ac = account.action_config
                            enable_rel_like = (acc_ac.enable_relevance_filter_likes if (acc_ac and acc_ac.enable_relevance_filter_likes is not None)
                                               else self.analysis_config.get('enable_relevance_filter', {}).get('likes', True))
                            thr_like = (acc_ac.relevance_threshold_likes if (acc_ac and acc_ac.relevance_threshold_likes is not None)
                                        else float(self.analysis_config.get('thresholds', {}).get('likes_min', 0.3)))
                            if enable_rel_like:
                                rel_like = await analyzer.score_relevance(tweet_candidate, keywords=account.target_keywords)
                                if rel_like < thr_like:
                                    continue
                        except Exception:
                            pass
                        # Avoid retweeting own tweets
                        if tweet_candidate.user_handle and self._is_own_tweet(tweet_candidate.user_handle, account, browser_manager):
                            continue
                        interaction_success = await publisher.retweet_tweet(tweet_candidate)
                        if interaction_success:
                            retweets_made += 1
                            metrics.increment('retweets')
                            metrics.log_event('retweet', 'success', {'source': 'keyword', 'keyword': keyword, 'tweet_id': tweet_candidate.tweet_id})
                            await asyncio.sleep(random.uniform(current_action_config.min_delay_between_actions_seconds, current_action_config.max_delay_between_actions_seconds))
                        else:
                            metrics.increment('errors')
                            metrics.log_event('retweet', 'failure', {'source': 'keyword', 'keyword': keyword, 'tweet_id': tweet_candidate.tweet_id})
                logger.info(f"[{account.account_id}] Finished keyword-based retweets.")


            # Action 3: Scrape news/research sites and post summaries/links
            news_sites_for_account = account.news_sites
            research_sites_for_account = account.research_paper_sites
            if current_action_config.enable_content_curation_posts and (news_sites_for_account or research_sites_for_account):
                 logger.info(f"[{account.account_id}] Content curation from news/research sites is planned.")
            elif current_action_config.enable_content_curation_posts:
                logger.info(f"[{account.account_id}] Content curation enabled, but no news/research sites configured for this account.")


            # Action 4: Like tweets
            if current_action_config.enable_liking_tweets:
                # Default to account target keywords if like list not configured
                keywords_to_like = current_action_config.like_tweets_from_keywords or (account.target_keywords or [])
                if keywords_to_like:
                    logger.info(f"[{account.account_id}] Starting to like tweets based on {len(keywords_to_like)} keywords.")
                    likes_done_this_run = 0
                    for keyword in keywords_to_like:
                        if likes_done_this_run >= current_action_config.max_likes_per_run:
                            break
                        logger.info(f"[{account.account_id}] Searching for tweets with keyword '{keyword}' to like.")
                        tweets_to_potentially_like = await asyncio.to_thread(
                            scraper.scrape_tweets_by_keyword,
                            keyword,
                            max_tweets=current_action_config.max_likes_per_run * 2 # Fetch more to have options
                        )
                        for tweet_to_like in tweets_to_potentially_like:
                            if likes_done_this_run >= current_action_config.max_likes_per_run:
                                break
                            
                            action_key = f"like_{account.account_id}_{tweet_to_like.tweet_id}"
                            if action_key in self.processed_action_keys:
                                logger.info(f"[{account.account_id}] Already liked or processed tweet {tweet_to_like.tweet_id}. Skipping.")
                                continue
                            
                            if current_action_config.avoid_replying_to_own_tweets and tweet_to_like.user_handle and self._is_own_tweet(tweet_to_like.user_handle, account, browser_manager):
                                logger.info(f"[{account.account_id}] Skipping own tweet {tweet_to_like.tweet_id} for liking.")
                                continue

                            # Optional relevance filter for likes pipeline (settings-driven)
                            try:
                                acc_ac = account.action_config
                                enable_rel_like = (acc_ac.enable_relevance_filter_likes if (acc_ac and acc_ac.enable_relevance_filter_likes is not None)
                                                   else self.analysis_config.get('enable_relevance_filter', {}).get('likes', True))
                                thr_like = (acc_ac.relevance_threshold_likes if (acc_ac and acc_ac.relevance_threshold_likes is not None)
                                            else float(self.analysis_config.get('thresholds', {}).get('likes_min', 0.3)))
                                if enable_rel_like:
                                    rel_like = await analyzer.score_relevance(tweet_to_like, keywords=account.target_keywords)
                                    if rel_like < thr_like:
                                        logger.debug(f"[{account.account_id}] Skipping like {tweet_to_like.tweet_id} (rel {rel_like:.2f} < {thr_like}).")
                                        continue
                            except Exception:
                                pass

                            logger.info(f"[{account.account_id}] Attempting to like tweet {tweet_to_like.tweet_id} from URL: {tweet_to_like.tweet_url}")
                            like_success = await engagement.like_tweet(tweet_id=tweet_to_like.tweet_id, tweet_url=str(tweet_to_like.tweet_url) if tweet_to_like.tweet_url else None)
                            metrics.log_event('like', 'success' if like_success else 'failure', {'tweet_id': tweet_to_like.tweet_id})
                            
                            if like_success:
                                self.file_handler.save_processed_action_key(action_key, timestamp=datetime.now().isoformat())
                                self.processed_action_keys.add(action_key)
                                likes_done_this_run += 1
                                await asyncio.sleep(random.uniform(current_action_config.min_delay_between_actions_seconds / 2, current_action_config.max_delay_between_actions_seconds / 2)) # Shorter delay for likes
                                metrics.increment('likes')
                            else:
                                logger.warning(f"[{account.account_id}] Failed to like tweet {tweet_to_like.tweet_id}.")
                                metrics.increment('errors')
                
                elif current_action_config.like_tweets_from_feed:
                    logger.warning(f"[{account.account_id}] Liking tweets from feed is enabled but not yet implemented.")
                else:
                    logger.info(f"[{account.account_id}] Liking tweets enabled, but no keywords specified and feed liking is off.")
            
            logger.info(f"[{account.account_id}] Finished processing tasks for this account.")

        except Exception as e:
            logger.error(f"[{account.account_id or 'UnknownAccount'}] Unhandled error during account processing: {e}", exc_info=True)
        finally:
            if browser_manager:
                browser_manager.close_driver()
            if metrics is not None:
                try:
                    metrics.mark_run_finish()
                except Exception:
                    pass
            # Safely log account ID
            account_id_for_log = account_dict.get('account_id', 'UnknownAccount')
            if 'account' in locals() and hasattr(account, 'account_id'):
                account_id_for_log = account.account_id
            logger.info(f"--- Finished processing for account: {account_id_for_log} ---")
            # The delay_between_accounts_seconds will now apply after each account finishes,
            # but accounts will start concurrently.
            # If a delay *between starts* is needed, a different mechanism (e.g., semaphore with delays) is required.
            await asyncio.sleep(self.global_settings.get('delay_between_accounts_seconds', 10)) # Reduced default for concurrent example

    async def run(self):
        logger.info("Twitter Orchestrator starting...")
        if not self.accounts_data:
            logger.warning("No accounts found in configuration. Orchestrator will exit.")
            return

        tasks = []
        for account_dict in self.accounts_data:
            tasks.append(self._process_account(account_dict))
        
        logger.info(f"Starting concurrent processing for {len(tasks)} accounts.")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            account_id = self.accounts_data[i].get('account_id', f"AccountIndex_{i}")
            if isinstance(result, Exception):
                logger.error(f"Error processing account {account_id}: {result}", exc_info=result)
            else:
                logger.info(f"Successfully completed processing for account {account_id}.")

        logger.info("Twitter Orchestrator finished processing all accounts.")


if __name__ == "__main__":
    orchestrator = TwitterOrchestrator()
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logger.info("Orchestrator run interrupted by user.")
    except Exception as e:
        logger.critical(f"Orchestrator failed with critical error: {e}", exc_info=True)
    finally:
        logger.info("Orchestrator shutdown complete.")
