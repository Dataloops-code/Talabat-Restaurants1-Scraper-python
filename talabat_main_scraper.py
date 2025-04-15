import asyncio
import nest_asyncio
from playwright.async_api import async_playwright
from typing import Optional, Dict, List
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FirefoxOptions
import time
from bs4 import BeautifulSoup
from collections import defaultdict
import re

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import Firefox

# Apply nest_asyncio at the module level
nest_asyncio.apply()


class TalabatScraper:
    def __init__(self):
        self.BASE_URL = "https://www.talabat.com"
        self.MAX_RETRIES = 4
        self.RETRY_DELAY = 3
        self.CLICK_WAIT_TIME = 4
        self.POPUP_WAIT_TIME = 3
        self.DEFAULT_TIMEOUT = 300000

    ### ALL RESTAURANTS ###
    async def get_restaurant_listings(self, area_url: str) -> List[Dict]:
        """
        Scrapes the restaurant listings from all pages using direct URL construction.
        First detects the last page number, then iterates through all pages.
        """
        browser = None
        all_restaurants = []

        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    }
                )
                page = await context.new_page()
                page.set_default_timeout(120000)  # Increase timeout to 120 seconds

                # First, load the first page to determine total pages
                print(f"Loading initial page: {area_url}")
                try:
                    response = await page.goto(area_url, wait_until='domcontentloaded')
                    if not response or not response.ok:
                        print(f"Failed to load initial page: {response.status if response else 'No response'}")
                        return []
                except Exception as e:
                    print(f"Error loading initial page: {str(e)}")
                    return []

                # Wait for content to load
                print("Waiting for initial content...")
                try:
                    await page.wait_for_selector(
                        "ul[data-test='pagination'], .vendor-card, [data-testid='restaurant-a']", timeout=30000)
                except Exception as e:
                    print(f"Error waiting for content: {e}")
                    # If we can't find pagination, try to extract restaurants from this page only
                    restaurants = await self._extract_restaurants_from_page(page, 1)
                    return restaurants

                # Find the last page number
                last_page = 1
                try:
                    # Look for pagination element
                    pagination = await page.query_selector("ul[data-test='pagination']")

                    if pagination:
                        # Find the second-to-last <li> element which should contain the last page number
                        pagination_items = await pagination.query_selector_all("li[data-testid='paginate-link']")

                        if pagination_items and len(pagination_items) > 1:
                            # Get the last numbered page item (second-to-last item in the list)
                            last_page_item = pagination_items[-2]  # The last one is the "Next" button

                            # Get the page number
                            last_page_link = await last_page_item.query_selector("a[page]")
                            if last_page_link:
                                last_page_attr = await last_page_link.get_attribute("page")
                                if last_page_attr and last_page_attr.isdigit():
                                    last_page = int(last_page_attr)
                                    print(f"Detected {last_page} total pages")

                    # If we couldn't find pagination or last page, assume it's just one page
                    if last_page == 1:
                        print("Could not detect pagination, scraping single page only")
                except Exception as e:
                    print(f"Error detecting pagination: {e}, defaulting to single page")
                    last_page = 1

                # Process each page
                for page_num in range(1, last_page + 1):
                    # Construct the URL for the current page
                    if page_num == 1:
                        current_url = area_url
                    else:
                        # Check if the base URL already has query parameters
                        if "?" in area_url:
                            # Add page parameter to existing query string
                            if "page=" in area_url:
                                # Replace existing page parameter
                                current_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
                            else:
                                # Add page parameter
                                current_url = f"{area_url}&page={page_num}"
                        else:
                            # Add page parameter as the first query parameter
                            current_url = f"{area_url}?page={page_num}"

                    print(f"\n--- Processing Page {page_num}/{last_page} ---")
                    print(f"URL: {current_url}")

                    # No need to load page 1 again
                    if page_num > 1:
                        try:
                            response = await page.goto(current_url, wait_until='domcontentloaded')
                            if not response or not response.ok:
                                print(
                                    f"Failed to load page {page_num}: {response.status if response else 'No response'}")
                                continue
                        except Exception as e:
                            print(f"Error loading page {page_num}: {str(e)}")
                            continue

                        # Wait for content to load
                        try:
                            await page.wait_for_selector(".vendor-card, [data-testid='restaurant-a']", timeout=30000)
                        except Exception as e:
                            print(f"Error waiting for restaurant cards on page {page_num}: {e}")
                            continue

                    # Extract restaurants from the current page
                    page_restaurants = await self._extract_restaurants_from_page(page, page_num)

                    # Add to our collection
                    all_restaurants.extend(page_restaurants)

                    print(f"Collected {len(page_restaurants)} restaurants from page {page_num}")

                    # Brief pause between pages to avoid being rate-limited
                    if page_num < last_page:
                        await asyncio.sleep(2)

                print(f"Successfully extracted data for {len(all_restaurants)} restaurants across {last_page} pages")
                return all_restaurants

        except Exception as e:
            print(f"Critical error in get_restaurant_listings: {e}")
            import traceback
            traceback.print_exc()
            return all_restaurants  # Return any restaurants we've collected so far
        finally:
            if browser:
                await browser.close()

    async def _extract_restaurants_from_page(self, page, page_num):
        """Helper method to extract restaurants from a loaded page."""
        restaurants = []

        # Progressive scroll to load all restaurants on current page
        print("Scrolling to load all content...")
        last_height = 0
        scroll_attempts = 0
        max_scroll_attempts = 20

        while scroll_attempts < max_scroll_attempts:
            # Scroll down
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)  # Wait for content to load

            # Get new scroll height
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break

            last_height = new_height
            scroll_attempts += 1

        # Extract restaurants from current page
        print(f"Extracting restaurant data from page {page_num}...")
        cards = await page.query_selector_all('a[data-testid="restaurant-a"]')
        print(f"Found {len(cards)} restaurant cards on page {page_num}")

        for index, card in enumerate(cards, 1):
            try:
                print(f"Processing restaurant {index}/{len(cards)} on page {page_num}")

                # Get content container
                content = await card.query_selector(".content")
                if not content:
                    print(f"No content container found for restaurant {index}")
                    continue

                # Extract name
                name_elem = await content.query_selector("h2")
                if not name_elem:
                    print(f"No name element found for restaurant {index}")
                    continue
                name = await name_elem.inner_text()

                # Extract cuisine
                cuisine_elem = await content.query_selector("div")
                cuisine = await cuisine_elem.inner_text() if cuisine_elem else "Unknown"

                # Get URL
                href = await card.get_attribute("href")
                if not href:
                    print(f"No URL found for restaurant {index}")
                    continue
                url = self.BASE_URL + href

                # Extract rating
                rating_elem = await content.query_selector('[data-testid="restaurant-rating-comp"]')
                rating = await rating_elem.inner_text() if rating_elem else "No rating"

                restaurant = {
                    "name": name,
                    "cuisine": cuisine,
                    "url": url,
                    "rating": rating,
                    "page": page_num  # Track which page this restaurant came from
                }

                # Extract delivery info
                spans = await content.query_selector_all("span")
                if spans:
                    try:
                        delivery_time = await spans[0].inner_text() if len(spans) > 0 else "N/A"
                        delivery_fee = (await spans[1].inner_text()).replace("Delivery:", "").strip() if len(
                            spans) > 1 else "N/A"
                        min_order = (await spans[2].inner_text()).replace("Min:", "").strip() if len(
                            spans) > 2 else "N/A"

                        restaurant.update({
                            "delivery_time": delivery_time,
                            "delivery_fee": delivery_fee,
                            "min_order": min_order
                        })
                    except Exception as e:
                        print(f"Error extracting delivery info for {name}: {e}")

                # Extract badges
                badges = await content.query_selector_all('.one-badge')
                if badges:
                    try:
                        tracking = await badges[0].inner_text() if len(badges) > 0 else "N/A"
                        contactless = await badges[1].inner_text() if len(badges) > 1 else "N/A"

                        restaurant.update({
                            "tracking_status": tracking,
                            "contactless": contactless
                        })
                    except Exception as e:
                        print(f"Error extracting badges for {name}: {e}")

                restaurants.append(restaurant)
                print(f"Successfully processed {name}")

            except Exception as e:
                print(f"Error processing restaurant card {index}: {e}")
                continue

        return restaurants

    ### RESTAURANTS' INFO ###
    async def get_restaurant_info(self, restaurant_url: str, max_retries: int = 3) -> Optional[Dict]:
        """Scrapes detailed information from a specific restaurant page with retry logic."""
        for attempt in range(max_retries):
            browser = None
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
                    context = await browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    )

                    page = await context.new_page()
                    # Increase timeout for problematic pages
                    page.set_default_timeout(120000)  # 2 minutes timeout

                    response = await page.goto(restaurant_url)
                    if response is None or not response.ok:
                        return None

                    # Wait for network idle with a more lenient timeout
                    try:
                        await page.wait_for_load_state('networkidle', timeout=30000)
                    except Exception as e:
                        print(f"Network idle timeout, continuing anyway: {str(e)}")
                        pass

                    # Extract Address
                    address_xpath = "xpath=/html/body/div/div/div[1]/div/div/div/div[2]/div/div/div/div/div[1]/div[1]/a/h1/small"
                    address_locator = page.locator(address_xpath)
                    extracted_data = {}

                    if await address_locator.is_visible():
                        extracted_data["Address"] = (await address_locator.inner_text()).replace("\xa0", " ")
                    else:
                        extracted_data["Address"] = "Not Available"

                    # Extract Reviews URL
                    reviews_url_xpath = "xpath=/html/body/div/div/div[1]/div/div/div/div[2]/div/div/div/div/div[1]/div[1]/a"
                    reviews_url_locator = page.locator(reviews_url_xpath)

                    if await reviews_url_locator.is_visible():
                        href = await reviews_url_locator.get_attribute("href")
                        if href:
                            extracted_data["Reviews URL"] = f"{self.BASE_URL}{href}"
                        else:
                            extracted_data["Reviews URL"] = "Not Available"
                    else:
                        extracted_data["Reviews URL"] = "Not Available"

                    # Find and Click Info Button
                    info_button_css = 'button:has-text("Info")'
                    info_button = page.locator(info_button_css)

                    if await info_button.is_visible():
                        await info_button.click(force=True)
                        await asyncio.sleep(2)
                    else:
                        return None

                    # Scroll to Load Info Section
                    info_section_css = '.col-md-11'

                    for _ in range(15):
                        await page.evaluate("window.scrollBy(0, 600)")
                        await asyncio.sleep(1)

                        if await page.locator(info_section_css).is_visible():
                            break
                    else:
                        return None

                    # Extract Additional Info Data
                    for i in range(1, 10):
                        label_xpath = f"xpath=/html/body/div/div/div[1]/div/div/div/div[3]/div/div[2]/div[1]/div/div[2]/div[{i}]/div[1]"
                        value_xpath = f"xpath=/html/body/div/div/div[1]/div/div/div/div[3]/div/div[2]/div[1]/div/div[2]/div[{i}]/div[2]"

                        label_locator = page.locator(label_xpath)
                        value_locator = page.locator(value_xpath)

                        if await label_locator.is_visible():
                            label_text = await label_locator.inner_text()

                            # Skip the Cuisines field since we already have it from the listing
                            if label_text.strip() == "Cuisines":
                                continue

                            if label_text.strip().lower() == "payment":
                                payment_methods = []
                                img_xpath = f"{value_xpath}/div/img"
                                img_elements = page.locator(img_xpath)

                                count = await img_elements.count()
                                for j in range(count):
                                    img_locator = img_elements.nth(j)
                                    alt_text = await img_locator.get_attribute("alt")
                                    if alt_text:
                                        payment_methods.append(alt_text)

                                extracted_data["Payment"] = payment_methods
                            else:
                                if await value_locator.is_visible():
                                    value_text = await value_locator.inner_text()
                                    extracted_data[label_text] = value_text
                                else:
                                    extracted_data[label_text] = ""
                        else:
                            break

                    return extracted_data

            except Exception as e:
                if "Timeout" in str(e):
                    if attempt < max_retries - 1:
                        print(f"Timeout occurred, attempt {attempt + 1}/{max_retries}. Retrying...")
                        await asyncio.sleep(5)  # Wait 5 seconds before retrying
                        continue
                    else:
                        print(f"Failed after {max_retries} attempts: {str(e)}")
                else:
                    print(f"Error scraping restaurant info: {str(e)}")
                return None

            finally:
                if browser:
                    await browser.close()

    ### RESTAURANTS' REVIEWS ###
    def get_reviews_data(self, reviews_url: str) -> Optional[Dict]:
        """
        Scrapes review data with enhanced extraction - collects up to 100 customer reviews.
        Will continue clicking "Read More" until either all reviews are loaded or 100 reviews are collected.
        """
        driver = None
        try:
            # Set up Firefox options
            firefox_options = FirefoxOptions()
            firefox_options.add_argument('--headless')
            firefox_options.add_argument('--window-size=1920,1080')
            firefox_options.add_argument('--disable-gpu')

            # Initialize Firefox WebDriver
            driver = webdriver.Firefox(options=firefox_options)
            driver.get(reviews_url)  # Using the passed parameter

            # Set explicit wait
            wait = WebDriverWait(driver, 15)

            # Wait for page to load
            print(f"Loading reviews page: {reviews_url}")
            time.sleep(5)

            try:
                # Get basic rating information
                rating_value = driver.find_element(
                    By.CSS_SELECTOR, "[data-testid='brand-rating-number']"
                ).text
                print(f"Found rating: {rating_value}")

                try:
                    ratings_number = driver.find_element(
                        By.CSS_SELECTOR, "[data-testid='brand-total-ratings']"
                    ).text
                except:
                    ratings_number = "0"
                    print("Could not find ratings number")

                try:
                    reviews_number = driver.find_element(
                        By.CSS_SELECTOR, "[data-testid='brand-total-reviews']"
                    ).text
                    reviews_count_text = reviews_number.strip()
                    # Extract just the number from text like "123 Reviews"
                    total_reviews = int(''.join(filter(str.isdigit, reviews_count_text)))
                    print(f"Total reviews available: {total_reviews}")
                except:
                    reviews_number = "0"
                    total_reviews = 0
                    print("Could not find reviews number")

                # *** Extract General Review Paragraphs ***
                review_paragraphs = []
                try:
                    # Look specifically for the markdown-rich-text-block div
                    markdown_div = driver.find_element(By.CSS_SELECTOR, ".markdown-rich-text-block")
                    if markdown_div:
                        paragraphs = markdown_div.find_elements(By.TAG_NAME, "p")
                        for p in paragraphs:
                            if p.text.strip():
                                review_paragraphs.append(p.text.strip())
                        print(f"Found {len(review_paragraphs)} general review paragraphs")
                except Exception as e:
                    print(f"Error extracting general review: {e}")
                    # Fallback method
                    try:
                        paragraphs = driver.find_elements(By.CSS_SELECTOR,
                                                          ".brand-reviews p, .restaurant-description p")
                        for p in paragraphs[:3]:
                            if p.text.strip():
                                review_paragraphs.append(p.text.strip())
                        print(f"Found {len(review_paragraphs)} general review paragraphs (fallback)")
                    except:
                        pass

                # Get specific reviews
                specific_reviews = {}
                specific_review_items = driver.find_elements(
                    By.CSS_SELECTOR, "[data-testid$='-rate']"
                )

                for item in specific_review_items:
                    try:
                        rating_text = item.text.strip().split('\n')
                        if len(rating_text) >= 2:
                            category = rating_text[-1]
                            rating = rating_text[0]
                            specific_reviews[category] = rating
                    except Exception as e:
                        print(f"Error extracting specific review: {e}")
                        continue

                # Click "Read More" button until we have 100 reviews or no more to load
                # Define maximum number of reviews to collect
                MAX_REVIEWS = 100

                # Maximum number of click attempts if there are technical issues
                MAX_CLICK_ATTEMPTS = 50

                # Track loaded reviews to avoid duplicates
                loaded_review_ids = set()
                actual_reviews = []

                # Flag to track if we should continue clicking
                continue_clicking = True
                clicks_completed = 0

                # Shorter wait time between clicks
                wait = WebDriverWait(driver, 7)

                # Keep clicking until we have enough reviews or can't click anymore
                while continue_clicking and clicks_completed < MAX_CLICK_ATTEMPTS:
                    try:
                        # Extract reviews that are currently loaded
                        current_reviews = driver.find_elements(
                            By.CSS_SELECTOR, "[data-testid='reviews-item-component']"
                        )

                        if not current_reviews:
                            # Try alternate selectors
                            current_reviews = driver.find_elements(
                                By.CSS_SELECTOR, ".review-item, .review-container"
                            )

                        # Process newly loaded reviews
                        new_reviews_found = 0
                        for review in current_reviews:
                            try:
                                # Create a unique ID for the review based on content
                                reviewer_name = "Unknown"
                                review_date = "Unknown date"
                                review_rating = "Unknown"
                                review_comment = "No comment"

                                try:
                                    # Customer name extraction
                                    reviewer_name = review.find_element(
                                        By.CSS_SELECTOR, "[data-testid='customer-name']"
                                    ).text.strip()
                                except:
                                    try:
                                        # Alternate method for name
                                        reviewer_name = review.find_element(
                                            By.CSS_SELECTOR, ".dark-gray.f-14.mt-1"
                                        ).text.strip()
                                    except:
                                        pass

                                try:
                                    # Date extraction
                                    review_date = review.find_element(
                                        By.CSS_SELECTOR, "div.dark-gray.ml-auto"
                                    ).text.strip()
                                except:
                                    pass

                                try:
                                    # Rating extraction
                                    rating_div = review.find_element(
                                        By.CSS_SELECTOR, "[data-testid='restaurant-rating-comp'] div.undefined"
                                    )
                                    review_rating = rating_div.text.strip()
                                except:
                                    try:
                                        # Alternate method to get rating
                                        rating_div = review.find_element(
                                            By.CSS_SELECTOR, ".rating-word div"
                                        )
                                        review_rating = rating_div.text.strip()
                                    except:
                                        pass

                                try:
                                    # Comment extraction
                                    review_comment = review.find_element(
                                        By.CSS_SELECTOR, "[data-testid='customer-review']"
                                    ).text.strip()
                                except:
                                    try:
                                        # Alternate method for comment
                                        review_comment = review.find_element(
                                            By.CSS_SELECTOR, "p.pt-2"
                                        ).text.strip()
                                    except:
                                        pass

                                # Create a unique ID using name, date and first 20 chars of comment
                                review_id = f"{reviewer_name}_{review_date}_{review_comment[:20]}"

                                # Only add if we haven't seen this review before
                                if review_id not in loaded_review_ids:
                                    loaded_review_ids.add(review_id)
                                    new_reviews_found += 1

                                    actual_reviews.append({
                                        "reviewer_name": reviewer_name,
                                        "review_date": review_date,
                                        "review_rating": review_rating,
                                        "review_comment": review_comment
                                    })
                            except Exception as e:
                                print(f"Error processing a review: {e}")
                                continue

                        print(f"Current review count: {len(actual_reviews)}/{MAX_REVIEWS}")

                        # Stop if we've hit our target
                        if len(actual_reviews) >= MAX_REVIEWS:
                            print(f"Reached target of {MAX_REVIEWS} reviews")
                            continue_clicking = False
                            break

                        # Stop if no new reviews were loaded
                        if new_reviews_found == 0 and clicks_completed > 0:
                            print("No new reviews found, likely reached the end")
                            continue_clicking = False
                            break

                        # Try to find the Read More button
                        print(f"\nAttempting to click Read More - {clicks_completed + 1}")

                        # Look for the button
                        button_selectors = [
                            (By.CSS_SELECTOR, "button[data-testid='read-more-button']"),
                            (By.XPATH, "//button[contains(text(), 'Read More')]"),
                            (By.XPATH, "//span[contains(text(), 'Read More')]/parent::button"),
                            (By.CSS_SELECTOR, ".text-amber.read-more-button"),
                            (By.XPATH, "//button[contains(@class, 'read-more')]")
                        ]

                        button = None
                        for by, selector in button_selectors:
                            try:
                                # Use presence_of_element_located for better reliability
                                elements = driver.find_elements(by, selector)
                                for element in elements:
                                    if element.is_displayed() and element.is_enabled():
                                        button = element
                                        break
                                if button:
                                    break
                            except:
                                continue

                        if not button:
                            print("No more Read More buttons found, all reviews loaded")
                            continue_clicking = False
                            break

                        # Scroll the button into view
                        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                                              button)
                        time.sleep(1)

                        # Try to click using multiple methods
                        click_successful = False
                        try:
                            # Try JavaScript click first (most reliable)
                            driver.execute_script("arguments[0].click();", button)
                            click_successful = True
                        except:
                            try:
                                # Try regular click if JavaScript click fails
                                button.click()
                                click_successful = True
                            except:
                                try:
                                    # Try ActionChains as last resort
                                    from selenium.webdriver.common.action_chains import ActionChains
                                    ActionChains(driver).move_to_element(button).click().perform()
                                    click_successful = True
                                except:
                                    print("Failed to click button using all methods")

                        if click_successful:
                            clicks_completed += 1
                            print(f"Successfully clicked Read More ({clicks_completed})")

                            # Wait for new content to load - shorter wait between clicks
                            time.sleep(2)
                        else:
                            print("Could not click the button, ending extraction")
                            continue_clicking = False

                    except Exception as e:
                        print(f"Error during click attempt {clicks_completed + 1}: {e}")
                        clicks_completed += 1

                        # If we've tried many times with errors, stop trying
                        if clicks_completed >= 10 and len(actual_reviews) == 0:
                            continue_clicking = False
                            break

                        # Brief pause before retry
                        time.sleep(1)

                print(f"\nCompleted {clicks_completed} Read More clicks")
                print(f"Successfully extracted {len(actual_reviews)} individual reviews")

                # Clean and format the data
                ratings_count = ''.join(filter(str.isdigit, ratings_number)) if ratings_number else "0"
                reviews_count = ''.join(filter(str.isdigit, reviews_number)) if reviews_number else "0"

                # Create the result dictionary
                result = {
                    "Rating_value": rating_value,
                    "Ratings_count": ratings_count,
                    "Reviews_count": reviews_count,
                    "General_review": review_paragraphs,
                    "Specific_reviews": specific_reviews,
                    "Customer_reviews": actual_reviews
                }

                return result

            except Exception as e:
                print(f"Error in review extraction: {e}")
                import traceback
                traceback.print_exc()
                return {
                    "Rating_value": "N/A",
                    "Error": str(e)
                }

        except Exception as e:
            print(f"Critical error in get_reviews_data: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    print(f"Error closing driver: {e}")

    
    ### EXPANDING CLOSED CATEGORIES ###
    def expand_menu_categories(self, driver):
        try:
            print("Expanding menu categories...")
            script = """
                const expandButtons = document.evaluate(
                    "//svg[contains(@class, 'fa-chevron-down')]",
                    document,
                    null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                    null
                );

                const clickedCount = [];
                for (let i = 0; i < expandButtons.snapshotLength; i++) {
                    const button = expandButtons.snapshotItem(i);
                    if (button && button.getAttribute('data-icon') === 'chevron-down') {
                        button.closest('div').click();
                        clickedCount.push(i);
                    }
                }
                return clickedCount.length;
            """
            clicked_count = driver.execute_script(script)
            print(f"Expanded {clicked_count} menu categories")
            time.sleep(2)
            return True
        except Exception as e:
            print(f"Error expanding menu categories: {e}")
            return False

    ### GETTING PRICE NORMALLY ###
    async def get_price_info_with_retry(self, item, max_retries=3):
        """Enhanced price info extraction with retry logic"""
        for attempt in range(max_retries):
            try:
                price_data = {
                    'old_price': None,
                    'new_price': None,
                    'price_on_selection': False
                }

                # Try multiple selectors for price container
                price_div = item.find('div', class_='text-right price-rating') or \
                            item.find('div', class_='price-container')

                if price_div:
                    # Extract old price if available
                    old_price_div = price_div.find('div', class_='lin-thr')
                    if old_price_div:
                        currency_span = old_price_div.find('span', class_='currency')
                        if currency_span:
                            price_data['old_price'] = currency_span.text.strip()

                    # Extract current price
                    price_divs = price_div.find_all('div', class_='mb-m-1')
                    for div in price_divs:
                        if not div.find('div', class_='lin-thr'):
                            currency_span = div.find('span', class_='currency')
                            if currency_span:
                                price_data['new_price'] = currency_span.text.strip()
                                break

                    # Check for price selection
                    price_selection = price_div.find('div', {'data-testid': 'price-on-selection'}) or \
                                      price_div.find('div', class_='price-selection')
                    if price_selection:
                        price_data['price_on_selection'] = True

                return price_data

            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Failed to extract price info after {max_retries} attempts: {e}")
                    return {}
                await asyncio.sleep(1)

        return {}

    ### RECEIPE DETAILS ###
    async def get_recipe_details_playwright(self, url, item_index, category_name=None, expected_name=None, retries=0,
                                            allow_fuzzy_match=False):
        """
        Enhanced recipe details extractor with navigation handling:
        1. Handles navigation events that might destroy execution context
        2. Implements reloading the page if necessary
        3. Improves modal detection and interaction
        4. Provides better error recovery
        """
        browser = None
        try:
            # Get the expected name from params or try to find it later
            if not expected_name and category_name:
                expected_name = "Linguine Pasta"  # Default for debugging

            print(f"\n=== EXTRACTING RECIPE DETAILS ===")
            print(f"Target: '{expected_name}' (suggested index: {item_index}, category: '{category_name}')")

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1200, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )

                # Create page with extended timeout
                page = await context.new_page()
                page.set_default_timeout(60000)  # 60 second timeout

                print(f"Loading page: {url}")
                try:
                    await page.goto(url, wait_until='networkidle', timeout=60000)
                    print("Page loaded successfully with networkidle")
                except Exception as e:
                    print(f"Network idle timeout, continuing anyway: {e}")
                    # Try to wait for DOM content at least
                    await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    print("Page loaded with domcontentloaded")

                # Wait for menu to load
                try:
                    await page.wait_for_selector("div.clickable", timeout=30000)
                    print("Menu loaded successfully")
                except Exception as e:
                    print(f"Error waiting for menu: {e}")
                    return None

                # Expand all collapsed categories with JavaScript
                try:
                    await page.evaluate("""
                        Array.from(document.querySelectorAll('svg[data-icon="chevron-down"]')).forEach(icon => {
                            const button = icon.closest('div');
                            if (button) button.click();
                        });
                    """)
                    await asyncio.sleep(1)
                    print("Expanded categories successfully")
                except Exception as e:
                    print(f"Warning: Could not expand categories: {e}")

                # Find all menu items
                all_items = await page.query_selector_all("div.clickable")
                print(f"Found {len(all_items)} total menu items")

                # First check: Is the index valid?
                if item_index >= len(all_items):
                    print(f"Warning: Item index {item_index} is out of range (max: {len(all_items) - 1})")
                    item_index = -1  # Force name-based search

                # Find the correct item either by index or by name
                target_item = None
                target_index = -1
                actual_name = None

                # Try index-based lookup first
                if item_index >= 0:
                    try:
                        possible_item = all_items[item_index]
                        name_elem = await possible_item.query_selector(
                            "div.item-name div.f-15, div[data-testid='item-name']")
                        if name_elem:
                            actual_name = await name_elem.inner_text()
                            print(f"Item at index {item_index}: '{actual_name}'")

                            # Check if it's the expected item
                            if expected_name and (actual_name.lower() == expected_name.lower() or
                                                  expected_name.lower() in actual_name.lower() or
                                                  actual_name.lower() in expected_name.lower()):
                                print(f"✓ Index-based lookup successful")
                                target_item = possible_item
                                target_index = item_index
                            else:
                                print(f"✗ Index points to wrong item, expected: '{expected_name}'")
                    except Exception as e:
                        print(f"Error in index-based lookup: {e}")

                # If index lookup failed, search for the item by name
                if not target_item and expected_name:
                    print(f"Searching for item by name: '{expected_name}'")

                    # JavaScript to find the item by name using a single parameter object
                    js_find_by_name = """
                    (params) => {
                        const expectedName = params.expectedName;
                        const allowFuzzyMatch = params.allowFuzzyMatch;

                        const items = Array.from(document.querySelectorAll('div.clickable'));
                        const result = {found: false, index: -1, name: null};

                        // First try exact match
                        for (let i = 0; i < items.length; i++) {
                            const nameElem = items[i].querySelector('div.item-name div.f-15, div[data-testid="item-name"]');
                            if (nameElem) {
                                const itemName = nameElem.textContent.trim();
                                // Check for exact match only
                                if (itemName.toLowerCase() === expectedName.toLowerCase()) {
                                    result.found = true;
                                    result.index = i;
                                    result.name = itemName;
                                    result.exact = true;
                                    break;
                                }
                            }
                        }

                        // If no exact match found, try partial matches
                        if (!result.found) {
                            for (let i = 0; i < items.length; i++) {
                                const nameElem = items[i].querySelector('div.item-name div.f-15, div[data-testid="item-name"]');
                                if (nameElem) {
                                    const itemName = nameElem.textContent.trim();

                                    // Check if expected name is contained in item name
                                    if (itemName.toLowerCase().includes(expectedName.toLowerCase()) || 
                                        expectedName.toLowerCase().includes(itemName.toLowerCase())) {
                                        result.found = true;
                                        result.index = i;
                                        result.name = itemName;
                                        result.exact = false;
                                        break;
                                    }
                                }
                            }
                        }

                        return result;
                    }
                    """

                    try:
                        search_result = await page.evaluate(js_find_by_name, {'expectedName': expected_name,
                                                                              'allowFuzzyMatch': allow_fuzzy_match})

                        if search_result['found']:
                            if search_result.get('exact', False):
                                print(
                                    f"✓ Found exact match: '{search_result['name']}' at index {search_result['index']}")
                                target_index = search_result['index']
                                target_item = all_items[target_index]
                                actual_name = search_result['name']
                            else:
                                print(
                                    f"✓ Found similar match: '{search_result['name']}' at index {search_result['index']}")
                                target_index = search_result['index']
                                target_item = all_items[target_index]
                                actual_name = search_result['name']
                        else:
                            print(f"✗ Could not find item with name '{expected_name}'")

                            # Try a more aggressive fuzzy search as last resort
                            try:
                                print("Trying more aggressive fuzzy search...")
                                js_fuzzy_search = """
                                (params) => {
                                    const partialName = params.partialName;
                                    const items = Array.from(document.querySelectorAll('div.clickable'));
                                    const partialNameLower = partialName.toLowerCase();
                                    const words = partialNameLower.split(' ').filter(w => w.length > 3);
                                    const candidates = [];

                                    // Match by words greater than 3 chars
                                    for (let i = 0; i < items.length; i++) {
                                        const nameElem = items[i].querySelector('div.item-name div.f-15, div[data-testid="item-name"]');
                                        if (nameElem) {
                                            const itemName = nameElem.textContent.trim().toLowerCase();

                                            for (const word of words) {
                                                if (itemName.includes(word)) {
                                                    candidates.push({
                                                        index: i,
                                                        name: nameElem.textContent.trim(),
                                                        relevance: word.length
                                                    });
                                                    break;
                                                }
                                            }
                                        }
                                    }

                                    // Sort by relevance and return top match
                                    if (candidates.length > 0) {
                                        candidates.sort((a, b) => b.relevance - a.relevance);
                                        return {
                                            found: true,
                                            index: candidates[0].index,
                                            name: candidates[0].name
                                        };
                                    }

                                    return {found: false};
                                }
                                """

                                fuzzy_result = await page.evaluate(js_fuzzy_search, {'partialName': expected_name})

                                if fuzzy_result['found']:
                                    print(
                                        f"✓ Found fuzzy match: '{fuzzy_result['name']}' at index {fuzzy_result['index']}")
                                    target_index = fuzzy_result['index']
                                    target_item = all_items[target_index]
                                    actual_name = fuzzy_result['name']
                                else:
                                    print(f"✗ No suitable items found")
                                    return None
                            except Exception as e:
                                print(f"Error in fuzzy search: {e}")
                                return None
                    except Exception as e:
                        print(f"Error in name search: {e}")
                        return None

                # If we still don't have a target item, give up
                if not target_item or target_index < 0:
                    print("Failed to identify the correct menu item")
                    return None

                # Scroll the item into view
                try:
                    await target_item.scroll_into_view_if_needed()
                    print(f"Target item: '{actual_name}' at index {target_index}")
                except Exception as e:
                    print(f"Warning: Could not scroll to item: {e}")

                # Extract options with robust error handling
                extracted_data = await self.extract_item_options(page, target_index, actual_name)
                if extracted_data:
                    return extracted_data

                # If we got here, try direct extraction
                try:
                    print("Trying direct click and extraction...")

                    # Track if the page is going to navigate
                    navigation_promise = page.wait_for_navigation(timeout=3000).catch(lambda _: None)

                    # Click the item
                    await target_item.click()

                    # Check if navigation occurred
                    navigation_result = await navigation_promise
                    if navigation_result:
                        print("Navigation detected after click. This is likely causing context destruction.")
                        return {
                            "title": actual_name,
                            # "options": [],
                            "price_details": {},
                            "error": "Navigation occurred during extraction"
                        }

                    # Wait for potential modal to appear
                    await asyncio.sleep(3)

                    # Look for modal
                    modal = await page.query_selector('div.modal, div[role="dialog"]')
                    if not modal:
                        print("No modal found after click")
                        return {
                            "title": actual_name,
                            # "options": [],
                            "price_details": {},
                            "error": "Modal not found"
                        }

                    # Try to extract content from modal
                    price_details = {}

                    # Look for accordions
                    accordions = await modal.query_selector_all('div[data-testid="accordion"]')
                    print(f"Found {len(accordions)} accordions")

                    for accordion in accordions:
                        title_elem = await accordion.query_selector('strong[data-test="sectionName"]')
                        type_elem = await accordion.query_selector('span.dark-gray.align-middle')

                        if title_elem:
                            section_title = await title_elem.inner_text()
                            section_type = await type_elem.inner_text() if type_elem else ""
                            full_title = f"{section_title} {section_type}"

                            options = []
                            # Get radio option labels with full item text
                            radio_labels = await accordion.query_selector_all('label[data-testid="radio"]')
                            option_set = set()

                            for label in radio_labels:
                                label_text = await label.inner_text()
                                if label_text.strip():
                                    clean_text = label_text.strip()
                                    clean_text = re.sub(r'\s+', ' ', clean_text)  # Normalize spaces

                                    # Skip pure price entries
                                    if re.match(r'^[\d.]+$', clean_text):
                                        continue

                                    # Skip just parenthesized prices
                                    if re.match(r'^\(\s*[\d.]+\s*\)$', clean_text):
                                        continue

                                    option_set.add(clean_text)

                            if option_set:
                                price_details[full_title] = list(option_set)

                    # Get raw options list too
                    options = []
                    radio_labels = await modal.query_selector_all('label[data-testid="radio"]')
                    option_set = set()

                    for label in radio_labels:
                        label_text = await label.inner_text()
                        if '(' in label_text and ')' in label_text:
                            # Try to extract clean "Name (Price)" format
                            price_match = re.search(r'([^(]+)\s*\(\s*([\d.]+)\s*\)', label_text)
                            if price_match:
                                clean_option = f"{price_match.group(1).strip()} ({price_match.group(2)})"
                                option_set.add(clean_option)

                    options = list(option_set)

                    # Close modal if possible
                    close_button = await modal.query_selector('button.close, [aria-label="Close"]')
                    if close_button:
                        await close_button.click()

                    if price_details or options:
                        return {
                            "title": actual_name,
                            # "options": options,
                            "price_details": price_details
                        }
                    else:
                        return {
                            "title": actual_name,
                            # "options": [],
                            "price_details": {},
                            "error": "No options found"
                        }
                except Exception as e:
                    print(f"Error in direct extraction: {e}")
                    return {
                        "title": actual_name,
                        # "options": [],
                        "price_details": {},
                        "error": str(e)
                    }

        except Exception as e:
            print(f"=== CRITICAL ERROR in recipe details (attempt {retries + 1}): {e} ===")
            if retries < self.MAX_RETRIES - 1:
                print(f"Retrying ({retries + 1}/{self.MAX_RETRIES})...")
                await asyncio.sleep(self.RETRY_DELAY)
                return await self.get_recipe_details_playwright(url, item_index, category_name, expected_name,
                                                                retries + 1, allow_fuzzy_match)
            return None

        finally:
            if browser:
                await browser.close()

    async def extract_item_options(self, page, target_index, item_name):
        """Extracts options from a menu item with enhanced error handling."""
        try:
            # JavaScript for robust option extraction
            js_extract_options = """
            (params) => {
                return new Promise((resolve) => {
                    const result = {
                        title: params.itemName,
                        options: [],
                        price_details: {}
                    };

                    // Open modal safely
                    try {
                        const items = document.querySelectorAll('div.clickable');
                        if (params.itemIndex >= items.length) {
                            resolve({...result, error: "Item index out of range"});
                            return;
                        }

                        // Store reference to the item
                        const targetItem = items[params.itemIndex];

                        // Click to open modal
                        targetItem.click();

                        // Wait for modal to appear and extract options
                        setTimeout(() => {
                            try {
                                const modal = document.querySelector('div.modal, div[role="dialog"], div.modal-body');
                                if (!modal) {
                                    resolve({...result, error: "Modal not found"});
                                    return;
                                }

                                // Get title from modal if available
                                const titleElement = modal.querySelector('strong[data-testid="title"], h4.modal-title');
                                if (titleElement) {
                                    result.title = titleElement.textContent.trim();
                                }

                                // Process accordions
                                const accordions = modal.querySelectorAll('div[data-testid="accordion"]');
                                accordions.forEach(accordion => {
                                    const titleElem = accordion.querySelector('strong[data-test="sectionName"]');
                                    const typeElem = accordion.querySelector('span.dark-gray.align-middle');

                                    if (titleElem) {
                                        const sectionTitle = titleElem.textContent.trim();
                                        const sectionType = typeElem ? typeElem.textContent.trim() : '';
                                        const fullTitle = `${sectionTitle} ${sectionType}`;

                                        // Create array for this section
                                        result.price_details[fullTitle] = [];

                                        // Get all radio options
                                        const options = new Set();
                                        const radioLabels = accordion.querySelectorAll('label[data-testid="radio"]');

                                        radioLabels.forEach(label => {
                                            const text = label.textContent.trim();
                                            // Skip pure price values and parenthesized prices
                                            if (/^[\\d.]+$/.test(text) || /^\\([\\d.]+\\)$/.test(text)) {
                                                return;
                                            }

                                            // Clean up text and normalize spaces
                                            const cleanText = text.replace(/\\s+/g, ' ');
                                            if (cleanText) {
                                                options.add(cleanText);
                                            }
                                        });

                                        // Add checkbox options
                                        const checkboxLabels = accordion.querySelectorAll('label.control-label');
                                        checkboxLabels.forEach(label => {
                                            const text = label.textContent.trim();
                                            // Skip pure price values and parenthesized prices
                                            if (/^[\\d.]+$/.test(text) || /^\\([\\d.]+\\)$/.test(text)) {
                                                return;
                                            }

                                            // Clean up text and normalize spaces
                                            const cleanText = text.replace(/\\s+/g, ' ');
                                            if (cleanText) {
                                                options.add(cleanText);
                                            }
                                        });

                                        // Convert set to array
                                        result.price_details[fullTitle] = Array.from(options);
                                    }
                                });

                                // Extract regular options
                                const optionSet = new Set();
                                const radioLabels = modal.querySelectorAll('label[data-testid="radio"]:not([data-accordion-item])');
                                radioLabels.forEach(label => {
                                    const text = label.textContent.trim();
                                    // Clean out any duplicate price entries
                                    if (/\\([\\d.]+\\)/.test(text)) {
                                        const cleanText = text.replace(/\\s+/g, ' ');
                                        const match = cleanText.match(/([^(]+)\\s*\\(([\\d.]+)\\)/);
                                        if (match) {
                                            optionSet.add(`${match[1].trim()} (${match[2]})`);
                                        } else {
                                            optionSet.add(cleanText);
                                        }
                                    }
                                });

                                result.options = Array.from(optionSet);

                                // Close modal if possible
                                const closeBtn = modal.querySelector('button.close, [aria-label="Close"]');
                                if (closeBtn) {
                                    closeBtn.click();
                                }

                                resolve(result);
                            } catch (error) {
                                resolve({...result, error: `Modal processing error: ${error.message}`});
                            }
                        }, 2000);
                    } catch (error) {
                        resolve({...result, error: `Click error: ${error.message}`});
                    }
                });
            }
            """

            # Execute with timeout handling
            print(f"Extracting options with enhanced error handling...")
            for attempt in range(3):
                try:
                    # Use asyncio.shield to prevent cancellation during cleanup
                    result = await page.evaluate(js_extract_options, {'itemIndex': target_index, 'itemName': item_name})

                    if result.get('error'):
                        print(f"Warning in extraction: {result['error']}")
                    else:
                        print(f"Successfully extracted options")

                    # Check if we have any useful data
                    has_options = len(result.get('options', [])) > 0
                    has_price_details = any(len(options) > 0 for options in result.get('price_details', {}).values())

                    if has_options or has_price_details:
                        # Clean up price details
                        price_details = {}
                        for category, options in result.get('price_details', {}).items():
                            if options and len(options) > 0:
                                # Filter out pure price entries and duplicates
                                cleaned_options = []
                                seen = set()
                                for option in options:
                                    # Skip pure price values
                                    if re.match(r'^[\d.]+$', option.strip()):
                                        continue
                                    # Skip parenthesized prices
                                    if re.match(r'^\(\s*[\d.]+\s*\)$', option.strip()):
                                        continue
                                    # Normalize option
                                    normalized = re.sub(r'\s+', ' ', option.strip())
                                    if normalized and normalized not in seen:
                                        seen.add(normalized)
                                        cleaned_options.append(normalized)

                                if cleaned_options:
                                    price_details[category] = cleaned_options

                        return {
                            "title": result.get('title', item_name),
                            # "options": result.get('options', []),
                            "price_details": price_details
                        }

                    print(f"No valid options found in attempt {attempt + 1}, retrying...")
                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"Error in extraction attempt {attempt + 1}: {e}")
                    await asyncio.sleep(2)

            return None

        except Exception as e:
            print(f"Critical error in extract_item_options: {e}")
            return None

    ### MENU EXTRACTION ###
    async def extract_item_data_with_retry(self, item, current_index, max_retries=3):
        """Enhanced item data extraction with all necessary fields"""
        for attempt in range(max_retries):
            try:
                item_data = {
                    'index': current_index,
                    'name': None,
                    'description': None,
                    'image_url': None,
                    'prices': {
                        'old_price': None,
                        'new_price': None,
                        'price_on_selection': False
                    }
                }

                # Name extraction
                name_selectors = [
                    ('div.item-name div.f-15', 'text'),
                    ('div.menu-item-name span.name', 'text'),
                    ('div[data-testid="item-name"]', 'text'),
                    ('h3.item-title', 'text'),
                    ('div.menu-item-title', 'text')
                ]

                for selector, attr in name_selectors:
                    try:
                        element = item.select_one(selector)
                        if element:
                            item_data['name'] = element.get_text(strip=True)
                            break
                    except Exception:
                        continue

                if not item_data['name']:
                    continue

                # Description extraction
                description_selectors = [
                    'div.item-name div.f-12',
                    'div.description',
                    'div[data-testid="item-description"]',
                    'p.item-desc'
                ]

                for selector in description_selectors:
                    try:
                        desc = item.select_one(selector)
                        if desc:
                            item_data['description'] = desc.get_text(strip=True)
                            break
                    except Exception:
                        continue

                # Price extraction
                price_div = item.find('div', class_='text-right price-rating') or \
                            item.find('div', class_='price-container')

                if price_div:
                    # Extract old price if available
                    old_price_div = price_div.find('div', class_='lin-thr')
                    if old_price_div:
                        currency_span = old_price_div.find('span', class_='currency')
                        if currency_span:
                            item_data['prices']['old_price'] = currency_span.text.strip()

                    # Extract current price
                    price_divs = price_div.find_all('div', class_='mb-m-1')
                    for div in price_divs:
                        if not div.find('div', class_='lin-thr'):
                            currency_span = div.find('span', class_='currency')
                            if currency_span:
                                item_data['prices']['new_price'] = currency_span.text.strip()
                                break

                    # Check for price selection
                    price_selection = price_div.find('div', {'data-testid': 'price-on-selection'}) or \
                                      price_div.find('div', class_='price-selection')
                    if price_selection:
                        item_data['prices']['price_on_selection'] = True

                # Image extraction
                image_selectors = [
                    ('img.item-image', 'src'),
                    ('img.menu-item-image', 'src'),
                    ('div.item-image img', 'src'),
                    ('picture img', 'src')
                ]

                for selector, attr in image_selectors:
                    try:
                        img = item.select_one(selector)
                        if img:
                            src = img.get(attr) or img.get('data-src')
                            if src:
                                item_data['image_url'] = src
                                break
                    except Exception:
                        continue

                if not item_data['image_url']:
                    item_data['image_url'] = '/assets/images/img-placeholder.svg'

                return item_data

            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Failed to extract item data after {max_retries} attempts: {e}")
                    return None
                await asyncio.sleep(1)

        return None

    async def get_menu_items(self, driver, url):
        """Enhanced menu items scraping with improved details handling"""
        try:
            # Initialize category expansion
            expansion_success = False
            for attempt in range(3):
                try:
                    if self.expand_menu_categories(driver):
                        expansion_success = True
                        break
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Category expansion attempt {attempt + 1} failed: {e}")

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            menu_selectors = [
                'div[data-testid="menu-category-list"]',
                'div.menu-categories',
                'div.restaurant-menu',
                'div.menu-container'
            ]

            menu_container = None
            for selector in menu_selectors:
                container = soup.select_one(selector)
                if container and container.find_all('div'):
                    menu_container = container
                    break

            if not menu_container:
                menu_container = soup

            menu_categories = {}
            global_item_index = 0  # Track global index across all categories

            category_selectors = [
                ('div[data-testid="menu-category"]', 'h4.category-title'),
                ('div.menu-category', 'h4.f-20'),
                ('div.category-container', 'div.category-name')
            ]

            categories = []
            for container_sel, title_sel in category_selectors:
                found_categories = menu_container.select(container_sel)
                if found_categories:
                    categories = found_categories
                    break

            print(f"Found {len(categories)} categories")

            # First pass: collect all items with basic data
            price_selection_items = []  # Track items needing extra details

            for category in categories:
                try:
                    category_name = None
                    name_selectors = [
                        'h4.f-20', 'h4.f-500', 'div.category-name',
                        'div[data-testid="category-name"]', 'h3.category-title'
                    ]

                    for selector in name_selectors:
                        name_element = category.select_one(selector)
                        if name_element:
                            category_name = name_element.get_text(strip=True)
                            break

                    if not category_name:
                        continue

                    print(f"\nProcessing category: {category_name}")
                    menu_categories[category_name] = []

                    item_selectors = [
                        'div.clickable',
                        'div.menu-item',
                        'div[data-testid="menu-item"]',
                        'div.item-container'
                    ]

                    items = []
                    for selector in item_selectors:
                        found_items = category.select(selector)
                        if found_items:
                            items = found_items
                            break

                    for item in items:
                        try:
                            item_data = await self.extract_item_data_with_retry(item, global_item_index)
                            if item_data:
                                # Store the item in its category
                                menu_categories[category_name].append(item_data)

                                # Track items needing extra details
                                if item_data['prices']['price_on_selection']:
                                    price_selection_items.append({
                                        'index': global_item_index,
                                        'name': item_data['name'],
                                        'category': category_name,
                                        'list_index': len(menu_categories[category_name]) - 1  # Index in category list
                                    })

                                global_item_index += 1

                        except Exception as e:
                            print(f"Error processing menu item: {e}")
                            global_item_index += 1  # Still increment index even on error
                            continue

                except Exception as e:
                    print(f"Error processing category: {e}")
                    continue

            # Second pass: fetch details for items with price on selection
            if price_selection_items:
                print(f"\nFetching extra details for {len(price_selection_items)} items...")

                for item_info in price_selection_items:
                    try:
                        item_name = item_info['name']
                        category = item_info['category']
                        list_index = item_info['list_index']
                        global_index = item_info['index']

                        print(f"Getting details for: {item_name} (index: {global_index}, category: {category})")

                        # Pass the expected item name to verify we get the right item
                        extra_details = await self.get_recipe_details_playwright(
                            url,
                            global_index,
                            category,
                            item_name  # Pass the expected name
                        )

                        if extra_details:
                            # Verify the title matches our expected item
                            expected = item_name.lower()
                            actual = extra_details['title'].lower() if extra_details.get('title') else ""

                            # Accept if titles are similar enough
                            if (expected == actual or
                                    expected in actual or
                                    actual in expected or
                                    # Fuzzy similarity check
                                    any(word in actual for word in expected.split() if len(word) > 3)):
                                print(f"Successfully got matching details for {item_name}")
                                menu_categories[category][list_index]['extra_details'] = extra_details
                            else:
                                print(f"Warning: Details title mismatch - Expected '{expected}', got '{actual}'")
                                # Store anyway but log the warning
                                menu_categories[category][list_index]['extra_details'] = extra_details
                        else:
                            print(f"Failed to get details for {item_name}")

                    except Exception as e:
                        print(f"Error getting extra details: {e}")

            # Remove empty categories
            menu_categories = {k: v for k, v in menu_categories.items() if v}

            # Print summary
            total_items = sum(len(items) for items in menu_categories.values())
            print(f"\nProcessed {len(menu_categories)} categories with {total_items} total items")

            return menu_categories

        except Exception as e:
            print(f"Critical error in get_menu_items: {e}")
            import traceback
            traceback.print_exc()
            return {}

    # async def get_restaurant_menu(self, url):
    #     """Menu scraping without timeouts"""
    #     driver = None
    #     try:
    #         options = FirefoxOptions()
    #         options.add_argument('--headless')
    #         options.add_argument('--window-size=1920,1080')
    #         options.add_argument('--disable-gpu')
    #         options.add_argument('--no-sandbox')
    #         options.add_argument('--disable-dev-shm-usage')

    #         # Disable all timeouts
    #         options.set_preference("page.load.timeout", 0)
    #         options.set_preference("browser.cache.disk.enable", False)
    #         options.set_preference("browser.cache.memory.enable", False)
    #         options.set_preference("browser.cache.offline.enable", False)
    #         options.set_preference("network.http.use-cache", False)

    #         max_retries = 3
    #         for attempt in range(max_retries):
    #             try:
    #                 driver = webdriver.Firefox(options=options)
    #                 driver.set_page_load_timeout(999999)  # Effectively disable timeout

    #                 print(f"Loading page (attempt {attempt + 1})...")
    #                 driver.get(url)

    #                 # Wait for menu elements without timeout
    #                 menu_selectors = [
    #                     "div[data-testid='menu-category']",
    #                     "div.menu-category",
    #                     "div.category-container"
    #                 ]

    #                 menu_found = False
    #                 while not menu_found:
    #                     for selector in menu_selectors:
    #                         elements = driver.find_elements(By.CSS_SELECTOR, selector)
    #                         if elements:
    #                             print(f"Found menu elements using selector: {selector}")
    #                             menu_found = True
    #                             break
    #                     if not menu_found:
    #                         print("Menu not found, waiting...")
    #                         await asyncio.sleep(5)

    #                 # Progressive scroll until all content is loaded
    #                 last_height = 0
    #                 same_height_count = 0

    #                 while True:
    #                     # Scroll in smaller increments
    #                     for _ in range(4):
    #                         driver.execute_script("window.scrollBy(0, 500);")
    #                         await asyncio.sleep(1)

    #                     # Scroll to bottom and check height
    #                     driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    #                     await asyncio.sleep(2)

    #                     new_height = driver.execute_script("return document.body.scrollHeight")

    #                     if new_height == last_height:
    #                         same_height_count += 1
    #                         if same_height_count >= 3:
    #                             print("Reached stable scroll position")
    #                             break
    #                     else:
    #                         same_height_count = 0
    #                         last_height = new_height

    #                     # Scroll back up slightly to trigger lazy loading
    #                     driver.execute_script(f"window.scrollTo(0, {new_height - 200});")
    #                     await asyncio.sleep(1)

    #                 # Get menu items without timeout
    #                 menu_items = await self.get_menu_items(driver, url)
    #                 if menu_items:
    #                     return menu_items

    #                 print("No menu items found, retrying...")

    #             except Exception as e:
    #                 print(f"Attempt {attempt + 1} failed: {e}")
    #                 if attempt < max_retries - 1:
    #                     await asyncio.sleep(10)
    #                 continue
    #             finally:
    #                 if driver:
    #                     try:
    #                         driver.quit()
    #                     except Exception:
    #                         pass

    #         return {}

    #     except Exception as e:
    #         print(f"Critical error in get_restaurant_menu: {e}")
    #         return {}

    async def get_restaurant_menu(self, url):
        """Menu scraping without timeouts"""
        driver = None
        try:
            options = FirefoxOptions()
            options.add_argument('--headless')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
    
            # Disable all timeouts
            options.set_preference("page.load.timeout", 0)
            options.set_preference("browser.cache.disk.enable", False)
            options.set_preference("browser.cache.memory.enable", False)
            options.set_preference("browser.cache.offline.enable", False)
            options.set_preference("network.http.use-cache", False)
    
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    driver = webdriver.Firefox(options=options)
                    driver.set_page_load_timeout(999999)  # Effectively disable timeout
    
                    print(f"Loading page (attempt {attempt + 1})...")
                    driver.get(url)
    
                    # Wait for menu elements without timeout
                    menu_selectors = [
                        "div[data-testid='menu-category']",
                        "div.menu-category",
                        "div.category-container"
                    ]
    
                    menu_found = False
                    trials = 0
                    max_trials = 5
                    while not menu_found and trials < max_trials:
                        for selector in menu_selectors:
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if elements:
                                print(f"Found menu elements using selector: {selector}")
                                menu_found = True
                                break
                        if not menu_found:
                            print("Menu not found, waiting...")
                            await asyncio.sleep(5)
                            trials += 1
    
                    if not menu_found and trials >= max_trials:
                        print("Menu not found after multiple trials, skipping...")
                        break
    
                    # Progressive scroll until all content is loaded
                    last_height = 0
                    same_height_count = 0
    
                    while True:
                        # Scroll in smaller increments
                        for _ in range(4):
                            driver.execute_script("window.scrollBy(0, 500);")
                            await asyncio.sleep(1)
    
                        # Scroll to bottom and check height
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        await asyncio.sleep(2)
    
                        new_height = driver.execute_script("return document.body.scrollHeight")
    
                        if new_height == last_height:
                            same_height_count += 1
                            if same_height_count >= 3:
                                print("Reached stable scroll position")
                                break
                        else:
                            same_height_count = 0
                            last_height = new_height
    
                        # Scroll back up slightly to trigger lazy loading
                        driver.execute_script(f"window.scrollTo(0, {new_height - 200});")
                        await asyncio.sleep(1)
    
                    # Get menu items without timeout
                    menu_items = await self.get_menu_items(driver, url)
                    if menu_items:
                        return menu_items
    
                    print("No menu items found, retrying...")
    
                except Exception as e:
                    print(f"Attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(10)
                    continue
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            pass
    
            return {}
    
        except Exception as e:
            print(f"Critical error in get_restaurant_menu: {e}")
            return {}

    ### COMBINING THE METHODS AND SCRAPING ALL RESTAURANTS FOR EACH PAGE ###
    async def scrape_all_restaurants_by_page(self, area_url: str, start_page: int = 7, start_restaurant: int = 4) -> List[Dict]:
        """Scrapes listing, info, reviews, and menu for all restaurants page by page."""
        full_data = []
        skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics", "Grocery, Hypermarket"}
    
        # First, load the first page to determine total pages
        print(f"Loading initial page: {area_url}")
    
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )
            page = await context.new_page()
            page.set_default_timeout(120000)  # Increase timeout to 120 seconds
    
            try:
                response = await page.goto(area_url, wait_until='domcontentloaded')
                if not response or not response.ok:
                    print(f"Failed to load initial page: {response.status if response else 'No response'}")
                    return []
            except Exception as e:
                print(f"Error loading initial page: {str(e)}")
                return []
    
            # Wait for content to load
            print("Waiting for initial content...")
            try:
                await page.wait_for_selector("ul[data-test='pagination'], .vendor-card, [data-testid='restaurant-a']",
                                             timeout=30000)
            except Exception as e:
                print(f"Error waiting for content: {e}")
                return []
    
            # Find the last page number
            last_page = 1
            try:
                # Look for pagination element
                pagination = await page.query_selector("ul[data-test='pagination']")
    
                if pagination:
                    # Find the second-to-last <li> element which should contain the last page number
                    pagination_items = await pagination.query_selector_all("li[data-testid='paginate-link']")
    
                    if pagination_items and len(pagination_items) > 1:
                        # Get the last numbered page item (second-to-last item in the list)
                        last_page_item = pagination_items[-2]  # The last one is the "Next" button
    
                        # Get the page number
                        last_page_link = await last_page_item.query_selector("a[page]")
                        if last_page_link:
                            last_page_attr = await last_page_link.get_attribute("page")
                            if last_page_attr and last_page_attr.isdigit():
                                last_page = int(last_page_attr)
                                print(f"Detected {last_page} total pages")
    
                # If we couldn't find pagination or last page, assume it's just one page
                if last_page == 1:
                    print("Could not detect pagination, scraping single page only")
            except Exception as e:
                print(f"Error detecting pagination: {e}, defaulting to single page")
                last_page = 1
    
            await browser.close()
    
        # Process each page
        for page_num in range(start_page, last_page + 1):
            # Construct the URL for the current page
            if page_num == 1:
                current_url = area_url
            else:
                # Check if the base URL already has query parameters
                if "?" in area_url:
                    # Add page parameter to existing query string
                    if "page=" in area_url:
                        # Replace existing page parameter
                        current_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
                    else:
                        # Add page parameter
                        current_url = f"{area_url}&page={page_num}"
                else:
                    # Add page parameter as the first query parameter
                    current_url = f"{area_url}?page={page_num}"
    
            print(f"\n=== Processing Page {page_num}/{last_page} ===")
            print(f"URL: {current_url}")
    
            # Scrape restaurants on current page
            page_restaurants = await self._extract_and_process_page(current_url, page_num, start_restaurant if page_num == start_page else 1)
    
            # Add to our collection
            full_data.extend(page_restaurants)
    
            # Save progress after each page
            try:
                with open(f'talabat_restaurants_page_{page_num}.json', 'w', encoding='utf-8') as f:
                    json.dump(page_restaurants, f, indent=2, ensure_ascii=False)
    
                with open('talabat_restaurants_progress.json', 'w', encoding='utf-8') as f:
                    json.dump(full_data, f, indent=2, ensure_ascii=False)
    
                print(f"Saved progress for page {page_num}")
            except Exception as e:
                print(f"Error saving progress for page {page_num}: {str(e)}")
    
            # Brief pause between pages to avoid being rate-limited
            if page_num < last_page:
                await asyncio.sleep(5)
    
        print(f"Successfully extracted data for {len(full_data)} restaurants across {last_page} pages")
        return full_data
    
    async def _extract_and_process_page(self, page_url, page_num, start_restaurant=1):
        """Extract restaurants from a page and process all their data."""
        # Get restaurants listing for this page
        page_restaurants = await self._get_page_restaurants(page_url, page_num)
        print(f"Collected {len(page_restaurants)} restaurants from page {page_num}")
    
        # Process each restaurant on this page
        for i, restaurant in enumerate(page_restaurants[start_restaurant - 1:], start_restaurant):
            try:
                skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics",
                                   "Grocery, Hypermarket"}
                if any(category in restaurant['cuisine'] for category in skip_categories):
                    print(f"\nSkipping {restaurant['name']} - Category: {restaurant['cuisine']}")
                    continue
    
                print(f"\nProcessing restaurant {i}/{len(page_restaurants)} on page {page_num}: {restaurant['name']}")
    
                restaurant['menu_items'] = {}
                restaurant['info'] = {}
                restaurant['reviews'] = {}
    
                try:
                    # Get menu data without timeout
                    print(f"Scraping menu for {restaurant['name']}...")
                    menu_data = await self.get_restaurant_menu(restaurant['url'])
                    if menu_data:
                        restaurant['menu_items'] = menu_data
                    else:
                        print(f"Failed to get menu for {restaurant['name']}")
    
                    # Get restaurant info with retry
                    info_data = await self.get_restaurant_info(restaurant['url'])
                    if info_data:
                        restaurant['info'] = info_data
    
                    # Get reviews if we have a reviews URL
                    if restaurant['info'].get('Reviews URL') and restaurant['info']['Reviews URL'] != 'Not Available':
                        print(f"Scraping reviews for {restaurant['name']}...")
                        reviews_data = self.get_reviews_data(restaurant['info']['Reviews URL'])
                        if reviews_data:
                            restaurant['reviews'] = reviews_data
    
                except Exception as e:
                    print(f"Error processing restaurant {restaurant['name']}: {str(e)}")
    
                # Brief delay between restaurants to avoid overwhelming the server
                await asyncio.sleep(2)
    
            except Exception as e:
                print(f"Critical error processing restaurant {restaurant['name']}: {str(e)}")
                continue
    
        return page_restaurants

    
    # async def scrape_all_restaurants_by_page(self, area_url: str) -> List[Dict]:
    #     """Scrapes listing, info, reviews, and menu for all restaurants page by page."""
    #     full_data = []
    #     skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics", "Grocery, Hypermarket"}

    #     # First, load the first page to determine total pages
    #     print(f"Loading initial page: {area_url}")

    #     async with async_playwright() as p:
    #         browser = await p.firefox.launch(headless=True)
    #         context = await browser.new_context(
    #             viewport={'width': 1920, 'height': 1080},
    #             user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    #         )
    #         page = await context.new_page()
    #         page.set_default_timeout(120000)  # Increase timeout to 120 seconds

    #         try:
    #             response = await page.goto(area_url, wait_until='domcontentloaded')
    #             if not response or not response.ok:
    #                 print(f"Failed to load initial page: {response.status if response else 'No response'}")
    #                 return []
    #         except Exception as e:
    #             print(f"Error loading initial page: {str(e)}")
    #             return []

    #         # Wait for content to load
    #         print("Waiting for initial content...")
    #         try:
    #             await page.wait_for_selector("ul[data-test='pagination'], .vendor-card, [data-testid='restaurant-a']",
    #                                          timeout=30000)
    #         except Exception as e:
    #             print(f"Error waiting for content: {e}")
    #             return []

    #         # Find the last page number
    #         last_page = 1
    #         try:
    #             # Look for pagination element
    #             pagination = await page.query_selector("ul[data-test='pagination']")

    #             if pagination:
    #                 # Find the second-to-last <li> element which should contain the last page number
    #                 pagination_items = await pagination.query_selector_all("li[data-testid='paginate-link']")

    #                 if pagination_items and len(pagination_items) > 1:
    #                     # Get the last numbered page item (second-to-last item in the list)
    #                     last_page_item = pagination_items[-2]  # The last one is the "Next" button

    #                     # Get the page number
    #                     last_page_link = await last_page_item.query_selector("a[page]")
    #                     if last_page_link:
    #                         last_page_attr = await last_page_link.get_attribute("page")
    #                         if last_page_attr and last_page_attr.isdigit():
    #                             last_page = int(last_page_attr)
    #                             print(f"Detected {last_page} total pages")

    #             # If we couldn't find pagination or last page, assume it's just one page
    #             if last_page == 1:
    #                 print("Could not detect pagination, scraping single page only")
    #         except Exception as e:
    #             print(f"Error detecting pagination: {e}, defaulting to single page")
    #             last_page = 1

    #         await browser.close()

    #     # Process each page
    #     for page_num in range(1, last_page + 1):
    #         # Construct the URL for the current page
    #         if page_num == 1:
    #             current_url = area_url
    #         else:
    #             # Check if the base URL already has query parameters
    #             if "?" in area_url:
    #                 # Add page parameter to existing query string
    #                 if "page=" in area_url:
    #                     # Replace existing page parameter
    #                     current_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
    #                 else:
    #                     # Add page parameter
    #                     current_url = f"{area_url}&page={page_num}"
    #             else:
    #                 # Add page parameter as the first query parameter
    #                 current_url = f"{area_url}?page={page_num}"

    #         print(f"\n=== Processing Page {page_num}/{last_page} ===")
    #         print(f"URL: {current_url}")

    #         # Scrape restaurants on current page
    #         page_restaurants = await self._extract_and_process_page(current_url, page_num)

    #         # Add to our collection
    #         full_data.extend(page_restaurants)

    #         # Save progress after each page
    #         try:
    #             with open(f'talabat_restaurants_page_{page_num}.json', 'w', encoding='utf-8') as f:
    #                 json.dump(page_restaurants, f, indent=2, ensure_ascii=False)

    #             with open('talabat_restaurants_progress.json', 'w', encoding='utf-8') as f:
    #                 json.dump(full_data, f, indent=2, ensure_ascii=False)

    #             print(f"Saved progress for page {page_num}")
    #         except Exception as e:
    #             print(f"Error saving progress for page {page_num}: {str(e)}")

    #         # Brief pause between pages to avoid being rate-limited
    #         if page_num < last_page:
    #             await asyncio.sleep(5)

    #     print(f"Successfully extracted data for {len(full_data)} restaurants across {last_page} pages")
    #     return full_data

    # async def _extract_and_process_page(self, page_url, page_num):
    #     """Extract restaurants from a page and process all their data."""
    #     # Get restaurants listing for this page
    #     page_restaurants = await self._get_page_restaurants(page_url, page_num)
    #     print(f"Collected {len(page_restaurants)} restaurants from page {page_num}")

    #     # Process each restaurant on this page
    #     for i, restaurant in enumerate(page_restaurants, 1):
    #         try:
    #             skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics",
    #                                "Grocery, Hypermarket"}
    #             if any(category in restaurant['cuisine'] for category in skip_categories):
    #                 print(f"\nSkipping {restaurant['name']} - Category: {restaurant['cuisine']}")
    #                 continue

    #             print(f"\nProcessing restaurant {i}/{len(page_restaurants)} on page {page_num}: {restaurant['name']}")

    #             restaurant['menu_items'] = {}
    #             restaurant['info'] = {}
    #             restaurant['reviews'] = {}

    #             try:
    #                 # Get menu data without timeout
    #                 print(f"Scraping menu for {restaurant['name']}...")
    #                 menu_data = await self.get_restaurant_menu(restaurant['url'])
    #                 if menu_data:
    #                     restaurant['menu_items'] = menu_data
    #                 else:
    #                     print(f"Failed to get menu for {restaurant['name']}")

    #                 # Get restaurant info with retry
    #                 info_data = await self.get_restaurant_info(restaurant['url'])
    #                 if info_data:
    #                     restaurant['info'] = info_data

    #                 # Get reviews if we have a reviews URL
    #                 if restaurant['info'].get('Reviews URL') and restaurant['info']['Reviews URL'] != 'Not Available':
    #                     print(f"Scraping reviews for {restaurant['name']}...")
    #                     reviews_data = self.get_reviews_data(restaurant['info']['Reviews URL'])
    #                     if reviews_data:
    #                         restaurant['reviews'] = reviews_data

    #             except Exception as e:
    #                 print(f"Error processing restaurant {restaurant['name']}: {str(e)}")

    #             # Brief delay between restaurants to avoid overwhelming the server
    #             await asyncio.sleep(2)

    #         except Exception as e:
    #             print(f"Critical error processing restaurant {restaurant['name']}: {str(e)}")
    #             continue

    #     return page_restaurants

    async def _get_page_restaurants(self, page_url, page_num):
        """Gets just the restaurant listings from a specific page."""
        browser = None
        page_restaurants = []

        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                page = await context.new_page()
                page.set_default_timeout(120000)  # Increase timeout to 120 seconds

                print(f"Loading page {page_num}: {page_url}")
                try:
                    response = await page.goto(page_url, wait_until='domcontentloaded')
                    if not response or not response.ok:
                        print(f"Failed to load page {page_num}: {response.status if response else 'No response'}")
                        return []
                except Exception as e:
                    print(f"Error loading page {page_num}: {str(e)}")
                    return []

                # Wait for content to load
                try:
                    await page.wait_for_selector(".vendor-card, [data-testid='restaurant-a']", timeout=30000)
                except Exception as e:
                    print(f"Error waiting for restaurant cards on page {page_num}: {e}")
                    return []

                # Extract restaurants from the current page
                page_restaurants = await self._extract_restaurants_from_page(page, page_num)

        except Exception as e:
            print(f"Critical error in _get_page_restaurants: {e}")
            import traceback
            traceback.print_exc()

        finally:
            if browser:
                await browser.close()

        return page_restaurants


# async def main():
#     """Main execution function."""
#     scraper = TalabatScraper()
#
#     # Example area URL - modify this to scrape different areas
#     area_url = "https://www.talabat.com/kuwait/restaurants/59/dhaher"
#
#     print("Starting scraper...")
#     results = await scraper.scrape_all_restaurants_by_page(area_url)
#
#     # Save results to JSON file with proper encoding
#     with open('talabat_restaurants.json', 'w', encoding='utf-8') as f:
#         json.dump(results, f, indent=2, ensure_ascii=False)
#
#     print(f"\nScraped {len(results)} restaurants successfully!")
#     print("Results saved to talabat_restaurants.json")
#
#
# if __name__ == "__main__":
#     asyncio.run(main())
