import sys
import os

if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

import re
import time
import logging
import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Optional, Set, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse
from datetime import datetime
import os

from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ScrapingConfig:
    base_url: str = "https://x.com"
    timeout: int = 30
    scroll_pause_time: float = 4.0
    max_scrolls: int = 200
    headless: bool = False
    wait_after_load: float = 10.0
    retry_attempts: int = 3
    manual_navigation_wait: int = 300 
    scroll_increment: int = 1000 
    max_consecutive_no_new_content: int = 10

    @classmethod
    def from_env(cls):
        """Create ScrapingConfig from environment variables with fallback to defaults"""
        return cls(
            timeout=int(os.getenv("TIMEOUT", 30)),
            scroll_pause_time=float(os.getenv("SCROLL_PAUSE_TIME", 4.0)),
            max_scrolls=int(os.getenv("MAX_SCROLLS", 200)),
            headless=os.getenv("HEADLESS", "False").lower() == "true",
            wait_after_load=float(os.getenv("WAIT_AFTER_LOAD", 10.0)),
            scroll_increment=int(os.getenv("SCROLL_INCREMENT", 1000)),
            max_consecutive_no_new_content=int(os.getenv("MAX_CONSECUTIVE_NO_NEW_CONTENT", 10))
        )

@dataclass
class PostData:
    post_id: str
    username: str
    full_url: str
    media_type: str
    original_href: str
    scraped_at: str = None
    
    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now().isoformat()

class CSVExporter:
    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or os.getenv("OUTPUT_DIR", "output")
        self._ensure_output_dir()
    
    def _ensure_output_dir(self) -> None:
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    def export_post_data(self, post_data_list: List[PostData], filename: str = None) -> str:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"twitter_posts_{timestamp}.csv"
        
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                if post_data_list:
                    fieldnames = list(asdict(post_data_list[0]).keys())
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    
                    writer.writeheader()
                    for post_data in post_data_list:
                        writer.writerow(asdict(post_data))
                
                logger.info(f"Exported {len(post_data_list)} posts to {filepath}")
                return filepath
                
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")
            raise
    
    def export_post_ids_only(self, post_data_list: List[PostData], filename: str = None) -> str:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"twitter_post_ids_{timestamp}.csv"
        
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['post_id'])
                
                for post_data in post_data_list:
                    writer.writerow([post_data.post_id])
                
                logger.info(f"Exported {len(post_data_list)} post IDs to {filepath}")
                return filepath
                
        except Exception as e:
            logger.error(f"Failed to export post IDs CSV: {e}")
            raise

class WebDriverManager(ABC):
    @abstractmethod
    def create_driver(self) -> webdriver.Chrome:
        pass
    
    @abstractmethod
    def quit_driver(self, driver: webdriver.Chrome) -> None:
        pass

class ChromeDriverManager(WebDriverManager):
    def __init__(self, config: ScrapingConfig):
        self.config = config
    
    def create_driver(self) -> webdriver.Chrome:
        options = Options()
        
        if self.config.headless:
            options.add_argument("--headless")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-gpu")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.set_page_load_timeout(self.config.timeout)
            driver.implicitly_wait(10)
            return driver
            
        except WebDriverException as e:
            logger.error(f"Failed to create Chrome driver: {e}")
            raise
    
    def quit_driver(self, driver: webdriver.Chrome) -> None:
        try:
            driver.quit()
        except Exception as e:
            logger.warning(f"Error while quitting driver: {e}")

class MediaGridExtractor:
    MEDIA_LINK_PATTERNS = [
        re.compile(r'/([^/]+)/status/(\d+)/video/(\d+)'),
        re.compile(r'/([^/]+)/status/(\d+)/photo/(\d+)'),
        re.compile(r'/status/(\d+)/video/(\d+)'),
        re.compile(r'/status/(\d+)/photo/(\d+)'),
        re.compile(r'/status/(\d+)'),
    ]
    
    def extract_media_posts_from_soup(self, soup: BeautifulSoup, username: str) -> Set[Tuple[str, str, str]]:
        posts = set()
        
        media_selectors = [
            'li[role="listitem"] a[href*="/video/"]',
            'li[role="listitem"] a[href*="/photo/"]',
            'a[href*="/status/"][href*="/video/"]',
            'a[href*="/status/"][href*="/photo/"]',
            'div[style*="calc(33.3333%"] a[href*="/status/"]',
            'li[role="listitem"] a[href*="/status/"]'
        ]
        
        for selector in media_selectors:
            links = soup.select(selector)
            logger.debug(f"Selector '{selector}' found {len(links)} links")
            
            for link in links:
                href = link.get('href', '')
                if href:
                    post_data = self._parse_media_href(href, username)
                    if post_data:
                        posts.add(post_data)
        
        return posts
    
    def extract_media_posts_from_elements(self, driver: webdriver.Chrome, username: str) -> Set[Tuple[str, str, str]]:
        posts = set()
        
        xpath_selectors = [
            "//li[@role='listitem']//a[contains(@href, '/video/')]",
            "//li[@role='listitem']//a[contains(@href, '/photo/')]",
            "//a[contains(@href, '/status/') and contains(@href, '/video/')]",
            "//a[contains(@href, '/status/') and contains(@href, '/photo/')]",
            "//li[@role='listitem']//a[contains(@href, '/status/')]"
        ]
        
        for xpath in xpath_selectors:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                logger.debug(f"XPath '{xpath}' found {len(elements)} elements")
                
                for element in elements:
                    try:
                        href = element.get_attribute('href')
                        if href:
                            post_data = self._parse_media_href(href, username)
                            if post_data:
                                posts.add(post_data)
                    except Exception as e:
                        logger.debug(f"Error extracting from element: {e}")
                        continue
                        
            except Exception as e:
                logger.warning(f"Error with XPath '{xpath}': {e}")
        
        return posts
    
    def _parse_media_href(self, href: str, username: str) -> Optional[Tuple[str, str, str]]:
        if not href:
            return None
        
        for pattern in self.MEDIA_LINK_PATTERNS:
            match = pattern.search(href)
            if match:
                groups = match.groups()
                
                if 'video' in href:
                    media_type = 'video'
                elif 'photo' in href:
                    media_type = 'photo'
                else:
                    media_type = 'unknown'
                
                if len(groups) >= 2 and groups[1].isdigit():
                    post_id = groups[1]
                elif len(groups) >= 1 and groups[0].isdigit():
                    post_id = groups[0]
                else:
                    continue
                
                return (post_id, media_type, href)
        
        return None


class AutoNavigationHandler:
    def __init__(self, driver: webdriver.Chrome, config: ScrapingConfig):
        self.driver = driver
        self.config = config
        self.wait = WebDriverWait(driver, config.timeout)
        self.twitter_username = os.getenv("TWITTER_USERNAME")
        self.twitter_password = os.getenv("TWITTER_PASSWORD")
    
    def auto_navigate_to_media(self, username: str) -> bool:
        strategies = [
            self._try_direct_media_access,
            self._try_home_then_media,
            self._try_auto_login_then_media,
            self._try_manual_login_then_media
        ]
        
        for i, strategy in enumerate(strategies):
            logger.info(f"Trying navigation strategy {i+1}/{len(strategies)}")
            try:
                if strategy(username):
                    return True
            except Exception as e:
                logger.warning(f"Strategy {i+1} failed: {e}")
                continue
        
        logger.error("All navigation strategies failed")
        return False
    
    def _try_direct_media_access(self, username: str) -> bool:
        logger.info("Strategy 1: Direct media page access")
        media_url = f"{self.config.base_url}/{username}/media"
        
        self.driver.get(media_url)
        time.sleep(self.config.wait_after_load)
        
        return self._verify_media_page_loaded()
    
    def _try_home_then_media(self, username: str) -> bool:
        logger.info("Strategy 2: Home page then media")
        
        self.driver.get(self.config.base_url)
        time.sleep(5)
        
        media_url = f"{self.config.base_url}/{username}/media"
        self.driver.get(media_url)
        time.sleep(self.config.wait_after_load)
        
        return self._verify_media_page_loaded()
    
    def _try_auto_login_then_media(self, username: str) -> bool:
        logger.info("Strategy 3: Automatic login")
        
        if not self.twitter_username or not self.twitter_password:
            logger.info("Twitter credentials not found in environment variables, skipping auto login")
            return False
        
        logger.info("Attempting automatic login with provided credentials")
        
        self.driver.get(f"{self.config.base_url}/login")
        time.sleep(3)
        
        try:
            logger.info("Step 1: Entering username...")
            username_selectors = [
                'input[name="text"]',
                'input[autocomplete="username"]',
                'input[type="text"]'
            ]
            
            username_input = None
            for selector in username_selectors:
                try:
                    username_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not username_input:
                logger.error("Could not find username input field")
                return False
            
            username_input.clear()
            username_input.send_keys(self.twitter_username)
            time.sleep(1)
            
            logger.info("Clicking 'Next' button...")
            next_button_selectors = [
                'button[type="button"]:not([aria-label]):not([data-testid]):nth-of-type(1)',
                'button[role="button"]:has(span:contains("次へ"))',
                'div[role="button"]:has(span:contains("次へ"))',
                'button[type="button"][style*="background-color: rgb(15, 20, 25)"]'
            ]
            
            next_button = None
            for selector in next_button_selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button[type="button"]')
                    for button in buttons:
                        button_text = button.text.strip()
                        style = button.get_attribute('style') or ''
                        if ('次へ' in button_text or 
                            'Next' in button_text or 
                            'background-color: rgb(15, 20, 25)' in style):
                            next_button = button
                            break
                    if next_button:
                        break
                except:
                    continue
            
            if not next_button:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button[type="button"]')
                for button in buttons:
                    if button.is_enabled() and button.is_displayed():
                        style = button.get_attribute('style') or ''
                        if 'background-color: rgb(15, 20, 25)' in style:
                            next_button = button
                            break
            
            if not next_button:
                logger.error("Could not find 'Next' button")
                return False
            
            next_button.click()
            time.sleep(3)
            
            logger.info("Step 2: Entering password...")
            password_selectors = [
                'input[name="password"]',
                'input[autocomplete="current-password"]',
                'input[type="password"]'
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    password_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not password_input:
                logger.error("Could not find password input field")
                return False
            
            password_input.clear()
            password_input.send_keys(self.twitter_password)
            time.sleep(1)
            
            logger.info("Clicking 'Login' button...")
            login_button = None
            buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button[type="button"]')
            for button in buttons:
                if button.is_enabled() and button.is_displayed():
                    button_text = button.text.strip()
                    style = button.get_attribute('style') or ''
                    if (('ログイン' in button_text or 'Login' in button_text or 'Log in' in button_text) or
                        ('background-color: rgb(15, 20, 25)' in style and len(button_text) < 10)):
                        login_button = button
                        break
            
            if not login_button:
                logger.error("Could not find 'Login' button")
                return False
            
            login_button.click()
            time.sleep(5)
            
            if self._verify_login_success():
                logger.info("Automatic login successful! Navigating to media page...")
                media_url = f"{self.config.base_url}/{username}/media"
                self.driver.get(media_url)
                time.sleep(self.config.wait_after_load)
                return self._verify_media_page_loaded()
            else:
                logger.error("Automatic login failed")
                return False
                
        except Exception as e:
            logger.error(f"Automatic login failed with error: {e}")
            return False
    
    def _try_manual_login_then_media(self, username: str) -> bool:
        logger.info("Strategy 4: Manual login with auto-detection")
        
        self.driver.get(f"{self.config.base_url}/login")
        
        print("\n" + "="*60)
        print("MANUAL LOGIN REQUIRED")
        print("="*60)
        print("Automatic login failed or credentials not provided.")
        print("1. Browser opened to X.com login page")
        print("2. Please log in manually in the browser")
        print("3. After login, the script will automatically navigate to media page")
        print("4. NO NEED TO PRESS ENTER - Script will detect login automatically")
        print("="*60)
        
        login_detected = self._wait_for_login_completion()
        
        if login_detected:
            logger.info("Login detected! Navigating to media page...")
            media_url = f"{self.config.base_url}/{username}/media"
            self.driver.get(media_url)
            time.sleep(self.config.wait_after_load)
            
            return self._verify_media_page_loaded()
        
        return False
    
    def _verify_login_success(self) -> bool:
        current_url = self.driver.current_url
        
        login_indicators = ['/login', '/flow/login', '/i/flow/login']
        if any(indicator in current_url for indicator in login_indicators):
            return False
        
        if ('/home' in current_url or 
            current_url.endswith('x.com/') or 
            current_url.endswith('x.com')):
            return True
        
        try:
            nav_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"]')
            if nav_elements:
                return True
                
            home_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]')
            if home_elements:
                return True
                
        except Exception:
            pass
        
        return False
    
    def _wait_for_login_completion(self, max_wait_time: int = 300) -> bool:
        logger.info("Waiting for login completion (max 5 minutes)...")
        
        start_time = time.time()
        login_indicators = ['/login', '/flow/login', '/i/flow/login']
        
        while time.time() - start_time < max_wait_time:
            current_url = self.driver.current_url
            
            if not any(indicator in current_url for indicator in login_indicators):
                logger.info(f"Login detected! Current URL: {current_url}")
                return True
            
            if '/home' in current_url or current_url.endswith('x.com/') or current_url.endswith('x.com'):
                logger.info(f"Home page detected! Current URL: {current_url}")
                return True
            
            time.sleep(2)
            
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and elapsed > 0:
                logger.info(f"Still waiting for login... ({elapsed}s elapsed)")
        
        logger.warning("Login detection timeout")
        return False
    
    def _verify_media_page_loaded(self) -> bool:
        current_url = self.driver.current_url
        
        if '/media' not in current_url:
            logger.warning(f"Not on media page. Current URL: {current_url}")
            return False
        
        media_indicators = [
            'li[role="listitem"]',
            '[data-testid="cellInnerDiv"]',
            'div[style*="calc(33.3333%"]',
            'a[href*="/video/"]',
            'a[href*="/photo/"]'
        ]
        
        for indicator in media_indicators:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, indicator)
                if elements:
                    logger.info(f"Media page verified! Found {len(elements)} elements with selector: {indicator}")
                    return True
            except Exception:
                continue
        
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            if len(page_text) > 500:
                logger.info("Media page has content, proceeding...")
                return True
        except Exception:
            pass
        
        logger.warning("Could not verify media page loaded properly")
        return False


class InfiniteScrollHandler:
    def __init__(self, driver: webdriver.Chrome, config: ScrapingConfig):
        self.driver = driver
        self.config = config
        self.action_chains = ActionChains(driver)
    
    def scroll_to_load_all_content(self, extractor: MediaGridExtractor, username: str) -> Set[Tuple[str, str, str]]:
        logger.info("Starting infinite scroll to load ALL media content")
        
        all_posts = set()
        consecutive_no_new = 0
        scroll_count = 0
        
        while scroll_count < self.config.max_scrolls and consecutive_no_new < self.config.max_consecutive_no_new_content:
            posts_before = len(all_posts)
            
            self._perform_scroll_action()
            
            time.sleep(self.config.scroll_pause_time)
            
            new_posts = self._extract_current_posts(extractor, username)
            all_posts.update(new_posts)
            
            posts_after = len(all_posts)
            new_posts_count = posts_after - posts_before
            
            if new_posts_count > 0:
                consecutive_no_new = 0
                logger.info(f"Scroll {scroll_count + 1}: Found {new_posts_count} new posts (Total: {posts_after})")
            else:
                consecutive_no_new += 1
                logger.info(f"Scroll {scroll_count + 1}: No new posts ({consecutive_no_new}/{self.config.max_consecutive_no_new_content}) (Total: {posts_after})")
            
            scroll_count += 1
            
            if scroll_count % 10 == 0:
                logger.info(f"[PROGRESS] {scroll_count} scrolls, {len(all_posts)} total posts found")
        
        logger.info(f"[FINISHED] Scrolling completed: {scroll_count} scrolls, {len(all_posts)} total posts")
        return all_posts
    
    def _perform_scroll_action(self):
        self.driver.execute_script(f"window.scrollBy(0, {self.config.scroll_increment});")
        time.sleep(0.5)
        
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            for _ in range(3):
                body.send_keys(Keys.PAGE_DOWN)
                time.sleep(0.2)
        except Exception:
            pass
    
    def _extract_current_posts(self, extractor: MediaGridExtractor, username: str) -> Set[Tuple[str, str, str]]:
        current_posts = set()
        
        try:
            html_content = self.driver.page_source
            soup = BeautifulSoup(html_content, 'html.parser')
            soup_posts = extractor.extract_media_posts_from_soup(soup, username)
            current_posts.update(soup_posts)
            
            element_posts = extractor.extract_media_posts_from_elements(self.driver, username)
            current_posts.update(element_posts)
            
        except Exception as e:
            logger.debug(f"Error extracting current posts: {e}")
        
        return current_posts


class TwitterMediaScraper:
    def __init__(self, 
                 driver_manager: WebDriverManager,
                 config: ScrapingConfig = None):
        self.driver_manager = driver_manager
        self.config = config or ScrapingConfig()
        self.extractor = MediaGridExtractor()
        self.exporter = CSVExporter()
        self.driver: Optional[webdriver.Chrome] = None
    
    def __enter__(self):
        self.driver = self.driver_manager.create_driver()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver_manager.quit_driver(self.driver)
    
    def scrape_user_media(self, username: str, auto_login: bool = True) -> List[PostData]:
        if not self.driver:
            raise RuntimeError("Driver not initialized. Use as context manager.")
        
        if auto_login:
            nav_handler = AutoNavigationHandler(self.driver, self.config)
            if not nav_handler.auto_navigate_to_media(username):
                logger.error("Automatic navigation failed")
                return []
        else:
            url = f"{self.config.base_url}/{username}/media"
            self.driver.get(url)
            time.sleep(self.config.wait_after_load)
        
        scroll_handler = InfiniteScrollHandler(self.driver, self.config)
        
        all_posts_data = scroll_handler.scroll_to_load_all_content(self.extractor, username)
        
        post_data_list = []
        for post_id, media_type, original_href in all_posts_data:
            full_url = f"{self.config.base_url}/{username}/status/{post_id}"
            post_data = PostData(
                post_id=post_id,
                username=username,
                full_url=full_url,
                media_type=media_type,
                original_href=original_href
            )
            post_data_list.append(post_data)
        
        post_data_list.sort(key=lambda x: int(x.post_id))
        
        logger.info(f"[COMPLETED] Scraping completed: {len(post_data_list)} media posts found")
        return post_data_list
    
    def scrape_and_export(self, username: str, auto_login: bool = True) -> Dict[str, str]:
        post_data_list = self.scrape_user_media(username, auto_login)
        
        exported_files = {}
        
        if post_data_list:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            full_data_file = self.exporter.export_post_data(
                post_data_list, 
                f"{username}_media_posts_full_{timestamp}.csv"
            )
            exported_files['full_data'] = full_data_file
            
            ids_only_file = self.exporter.export_post_ids_only(
                post_data_list,
                f"{username}_media_post_ids_{timestamp}.csv"
            )
            exported_files['ids_only'] = ids_only_file
        
        return exported_files

def main():
    # Load configuration from environment variables
    config = ScrapingConfig.from_env()
    
    # Get target username from environment variable
    username = os.getenv("TARGET_USERNAME")
    if not username:
        logger.error("TARGET_USERNAME not set in environment variables")
        print("ERROR: Please set TARGET_USERNAME in your .env file")
        sys.exit(1)
    
    driver_manager = ChromeDriverManager(config)
    
    try:
        with TwitterMediaScraper(driver_manager, config) as scraper:
            logger.info(f"[START] Starting media scraping for @{username}")
            
            post_data_list = scraper.scrape_user_media(username, auto_login=True)
            
            if post_data_list:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                full_data_file = scraper.exporter.export_post_data(
                    post_data_list, 
                    f"{username}_media_posts_full_{timestamp}.csv"
                )
                
                ids_only_file = scraper.exporter.export_post_ids_only(
                    post_data_list,
                    f"{username}_media_post_ids_{timestamp}.csv"
                )
                
                exported_files = {
                    'full_data': full_data_file,
                    'ids_only': ids_only_file
                }
                
                print(f"\nSUCCESS! Found {len(post_data_list)} media posts for @{username}")
                print("="*70)
                
                video_count = sum(1 for p in post_data_list if p.media_type == 'video')
                photo_count = sum(1 for p in post_data_list if p.media_type == 'photo')
                other_count = len(post_data_list) - video_count - photo_count
                
                print(f"[VIDEOS] {video_count}")
                print(f"[PHOTOS] {photo_count}")
                print(f"[OTHER] {other_count}")
                print("="*70)
                
                print("[SAMPLE] Sample posts (first 10):")
                for i, post_data in enumerate(post_data_list[:10]):
                    print(f"  {i+1:2d}. {post_data.post_id} ({post_data.media_type})")
                
                if len(post_data_list) > 10:
                    print(f"  ... and {len(post_data_list) - 10} more")
                
                print("="*70)
                
                if exported_files:
                    print("[FILES] Exported files:")
                    for file_type, filepath in exported_files.items():
                        print(f"  {file_type}: {filepath}")
                
                post_ids = [post.post_id for post in post_data_list]
                print(f"\n[POST_IDS] All Post IDs ({len(post_ids)} total):")
                print(post_ids)
                
            else:
                print("ERROR: No media posts found.")
                print("HELP: Make sure you:")
                print("   1. Successfully logged in when prompted")
                print("   2. Script automatically navigated to the media page")
                print("   3. Media grid was visible before scraping started")
                
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise

if __name__ == "__main__":
    main()