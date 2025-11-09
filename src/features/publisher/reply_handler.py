import logging
import time
import random
from typing import Optional, Set

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

from core.browser_manager import BrowserManager
from data_models import ScrapedTweet, AccountConfig

logger = logging.getLogger(__name__)


def _normalize_handle(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return value.lstrip('@').split('?')[0].strip('/').lower() or None


def _collect_existing_reply_links(driver, handle: str) -> Set[str]:
    if not handle:
        return set()
    xpath = (
        f"//article[@role='article']//a[contains(@href, '/{handle}/status/') and contains(@href, '/status/') and @role='link']"
    )
    links: Set[str] = set()
    try:
        for anchor in driver.find_elements(By.XPATH, xpath):
            href = anchor.get_attribute('href')
            if href and f"/{handle}/status/" in href:
                links.add(href)
    except Exception:
        return set()
    return links


def reply_to_tweet(
    browser_manager: BrowserManager,
    original_tweet: ScrapedTweet,
    reply_text: str,
    account_config: Optional[AccountConfig] = None,
) -> bool:
    driver = browser_manager.get_driver()
    time.sleep(random.uniform(0.8, 2.2))  # Human-like jitter

    if not original_tweet.tweet_url:
        logger.error(f"Cannot reply to tweet {original_tweet.tweet_id}: Missing tweet URL.")
        return False
    if not reply_text:
        logger.error(f"Cannot reply to tweet {original_tweet.tweet_id}: Reply text is empty.")
        return False

    logger.info(
        f"Attempting to reply to tweet {original_tweet.tweet_id} with text: '{reply_text[:50]}...'"
    )

    own_handles: Set[str] = set()
    if account_config:
        if account_config.self_handles:
            own_handles.update(
                filter(None, (_normalize_handle(handle) for handle in account_config.self_handles))
            )
        normalized_account_id = _normalize_handle(account_config.account_id)
        if normalized_account_id:
            own_handles.add(normalized_account_id)
    detected_handle = _normalize_handle(getattr(browser_manager, 'logged_in_handle', None))
    if detected_handle:
        own_handles.add(detected_handle)

    primary_handle = next(iter(own_handles)) if own_handles else None
    pre_existing_replies: Set[str] = set()
    if primary_handle:
        try:
            pre_existing_replies = _collect_existing_reply_links(driver, primary_handle)
        except Exception:
            pre_existing_replies = set()

    try:
        browser_manager.navigate_to(str(original_tweet.tweet_url))
        time.sleep(3)

        main_tweet_article_xpath = (
            f"//article[.//a[contains(@href, '/status/{original_tweet.tweet_id}')]]"
        )
        main_tweet_element = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, main_tweet_article_xpath))
        )

        reply_icon_button = WebDriverWait(main_tweet_element, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//button[@data-testid='reply']"))
        )
        reply_icon_button.click()
        logger.info(f"Clicked reply icon for tweet {original_tweet.tweet_id}.")
        time.sleep(2)

        dialog = None
        try:
            dialog = WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='dialog' and @aria-modal='true']"))
            )
        except TimeoutException:
            dialog = None

        reply_text_area = None
        search_scopes = []
        if dialog is not None:
            search_scopes.append((dialog, ".//div[@data-testid='tweetTextarea_0' and @role='textbox']"))
        search_scopes.append((driver, "//div[@data-testid='tweetTextarea_0' and @role='textbox']"))
        search_scopes.append((driver, "//div[@data-testid='tweetTextarea_0']"))

        last_error = None
        for scope, xpath in search_scopes:
            try:
                reply_text_area = WebDriverWait(scope, 18).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                break
            except Exception as err:
                last_error = err
                continue
        if not reply_text_area:
            raise TimeoutException(f"Reply textarea not found. Last error: {last_error}")

        try:
            reply_text_area.click()
            reply_text_area.send_keys(Keys.CONTROL, "a")
            reply_text_area.send_keys(Keys.BACKSPACE)
        except Exception:
            pass

        safe_reply = (reply_text or "")[:270]
        reply_text_area.send_keys(safe_reply)
        logger.info("Typed reply text into textarea.")

        try:
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "[data-testid='twc-cc-mask']"))
            )
        except Exception:
            pass

        def find_enabled_reply_button():
            try:
                scope = dialog if dialog is not None else driver
                button = scope.find_element(
                    By.XPATH,
                    ".//button[@data-testid='tweetButton' and not(@disabled) and not(@aria-disabled='true')]",
                )
                return button
            except Exception:
                return None

        reply_post_button = None
        for _ in range(3):
            reply_post_button = find_enabled_reply_button()
            if reply_post_button:
                break
            try:
                reply_text_area.send_keys(" ")
                reply_text_area.send_keys(Keys.BACKSPACE)
            except Exception:
                pass
            time.sleep(0.5)

        submission_attempted = False

        if reply_post_button:
            try:
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});",
                        reply_post_button,
                    )
                except Exception:
                    pass
                reply_post_button.click()
                submission_attempted = True
            except ElementClickInterceptedException:
                logger.warning("Reply button click intercepted, trying JS click.")
                try:
                    driver.execute_script("arguments[0].click();", reply_post_button)
                    submission_attempted = True
                except Exception:
                    logger.warning("JS click failed; sending Ctrl+Enter as fallback for reply.")
            except Exception as click_error:
                logger.warning(f"Reply button click failed ({click_error}), falling back to keyboard submit.")

        if not submission_attempted:
            if reply_post_button:
                try:
                    reply_text_area.send_keys(Keys.CONTROL, Keys.ENTER)
                    submission_attempted = True
                except Exception:
                    pass

        if not submission_attempted:
            logger.warning("Reply button still disabled; attempting Ctrl+Enter fallback.")
            try:
                reply_text_area.send_keys(Keys.CONTROL, Keys.ENTER)
                submission_attempted = True
            except Exception as first_keyboard_error:
                logger.warning(f"Failed Ctrl+Enter submit attempt: {first_keyboard_error}")
                try:
                    new_dialog = None
                    try:
                        new_dialog = WebDriverWait(driver, 6).until(
                            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog' and @aria-modal='true']"))
                        )
                    except Exception:
                        new_dialog = None
                    new_scope = new_dialog if new_dialog is not None else driver
                    new_textarea = WebDriverWait(new_scope, 6).until(
                        EC.presence_of_element_located((By.XPATH, "//div[@data-testid='tweetTextarea_0']"))
                    )
                    new_textarea.send_keys(Keys.ENTER)
                    submission_attempted = True
                except Exception as second_keyboard_error:
                    logger.error(
                        f"Failed to submit reply via keyboard fallback: {second_keyboard_error}"
                    )
                    return False

        if not submission_attempted:
            logger.error("Reply submission could not be triggered.")
            return False

        logger.info("Triggered reply submission.")

        try:
            error_candidate = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//*[contains(., 'Try again') or contains(., 'rate limit') or contains(., 'over the limit') or contains(., 'went wrong')]",
                ))
            )
            logger.warning(
                f"Reply may have failed due to platform limits or errors: {(error_candidate.text or '').strip()}"
            )
        except Exception:
            pass

        try:
            if dialog is not None:
                WebDriverWait(driver, 10).until(EC.staleness_of(dialog))
        except Exception:
            time.sleep(2)

        time.sleep(random.uniform(1.2, 2.6))

        if primary_handle:
            try:
                WebDriverWait(driver, 12).until(
                    lambda d: _collect_existing_reply_links(d, primary_handle) - pre_existing_replies
                )
                logger.info("Detected new reply from our account in conversation thread.")
                return True
            except TimeoutException:
                logger.warning("Could not confirm reply appearance in-thread; refreshing once to verify.")
                try:
                    driver.refresh()
                    time.sleep(4)
                    new_links = _collect_existing_reply_links(driver, primary_handle)
                    if new_links - pre_existing_replies:
                        logger.info("Reply confirmed after refresh.")
                        return True
                except Exception as refresh_error:
                    logger.error(f"Refresh verification failed: {refresh_error}")
                logger.error("Reply not detected after verification attempts.")
                return False

        return True
    except TimeoutException as timeout_error:
        logger.error(
            f"Timeout while trying to reply to tweet {original_tweet.tweet_id}: {timeout_error}"
        )
        return False
    except Exception as generic_error:
        logger.error(
            f"Failed to reply to tweet {original_tweet.tweet_id}: {generic_error}", exc_info=True
        )
        return False
