import asyncio
import json
import os
import sys
import subprocess
import re  # Ensure re is imported for regex operations
from typing import Dict, List, Tuple
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter
from playwright.async_api import async_playwright  # Add this import
from talabat_main_scraper import TalabatScraper
from SavingOnDrive import SavingOnDrive


class MainScraper:
    def __init__(self):
        self.talabat_scraper = TalabatScraper()
        self.output_dir = "output"
        self.drive_uploader = SavingOnDrive('credentials.json')
        self.progress_file = "progress.json"
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load progress if exists
        self.progress = self.load_progress()
        
        # Ensure Playwright browsers are installed
        self.ensure_playwright_browsers()

    def ensure_playwright_browsers(self):
        """Ensure Playwright browsers are properly installed"""
        try:
            print("Installing Playwright browsers...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "firefox"], 
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Playwright browsers installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"Error installing Playwright browsers: {e}")
            print(f"STDOUT: {e.stdout.decode() if e.stdout else 'None'}")
            print(f"STDERR: {e.stderr.decode() if e.stderr else 'None'}")
            print("Will continue and let TalabatScraper try to handle browser fallbacks")
    
    def load_progress(self) -> Dict:
        """Load progress from JSON file if it exists with comprehensive error checking"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                print(f"Loaded progress from {self.progress_file}")
                
                # Log current progress state
                print(f"Current area index: {progress.get('current_area_index', 0)}")
                print(f"Completed areas: {len(progress.get('completed_areas', []))}")
                
                # Log more detailed progress
                if 'current_progress' in progress:
                    curr = progress['current_progress']
                    print(f"Current status: Area {curr.get('area_name', 'None')} - "
                          f"Page {curr.get('current_page', 0)}/{curr.get('total_pages', 0)} - "
                          f"Restaurant {curr.get('current_restaurant', 0)}/{curr.get('total_restaurants', 0)}")
                
                # Ensure all required keys exist with proper default values
                if 'completed_areas' not in progress:
                    progress['completed_areas'] = []
                if 'current_area_index' not in progress:
                    progress['current_area_index'] = 0
                if 'all_results' not in progress:
                    progress['all_results'] = {}
                if 'last_updated' not in progress:
                    progress['last_updated'] = None
                
                # Ensure current_progress structure is complete
                if 'current_progress' not in progress:
                    progress['current_progress'] = {
                        'area_name': None,
                        'current_page': 0, 
                        'total_pages': 0,
                        'current_restaurant': 0,
                        'total_restaurants': 0,
                        'processed_restaurants': [],
                        'completed_pages': []
                    }
                else:
                    # Ensure all keys exist in current_progress
                    curr_progress = progress['current_progress']
                    if 'area_name' not in curr_progress:
                        curr_progress['area_name'] = None
                    if 'current_page' not in curr_progress:
                        curr_progress['current_page'] = 0
                    if 'total_pages' not in curr_progress:
                        curr_progress['total_pages'] = 0
                    if 'current_restaurant' not in curr_progress:
                        curr_progress['current_restaurant'] = 0
                    if 'total_restaurants' not in curr_progress:
                        curr_progress['total_restaurants'] = 0
                    if 'processed_restaurants' not in curr_progress:
                        curr_progress['processed_restaurants'] = []
                    if 'completed_pages' not in curr_progress:
                        curr_progress['completed_pages'] = []
                
                return progress
            except Exception as e:
                print(f"Error loading progress file: {str(e)}")
                print("Creating new progress file...")
        
        # Return default empty progress
        default_progress = {
            "completed_areas": [],
            "current_area_index": 0,
            "last_updated": None,
            "all_results": {},
            "current_progress": {
                "area_name": None,
                "current_page": 0,
                "total_pages": 0,
                "current_restaurant": 0,
                "total_restaurants": 0,
                "processed_restaurants": [],
                "completed_pages": []
            }
        }
        
        # Save the default progress to ensure the file exists
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(default_progress, f, indent=2, ensure_ascii=False)
        
        print("Created new default progress file")
        return default_progress

    def print_progress_details(self):
        """Print the details of progress including all results and each restaurant scraped"""
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            print(json.dumps(progress, indent=2, ensure_ascii=False))

            if 'all_results' in progress:
                for area, results in progress['all_results'].items():
                    print(f"\nArea: {area}")
                    for restaurant in results:
                        print(json.dumps(restaurant, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Error reading progress file: {str(e)}")

    def save_progress(self):
        """Save current progress to JSON file and cache key with timestamp"""
        try:
            # Update timestamp
            import datetime
            self.progress["last_updated"] = datetime.datetime.now().isoformat()
            
            # Save to progress.json file
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=2, ensure_ascii=False)
            print(f"Saved progress to {self.progress_file}")
    
            # Save to cache key
            with open("talabat-scraper-progress-latest", 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=2, ensure_ascii=False)
            print(f"Saved progress to talabat-scraper-progress-latest")
    
        except Exception as e:
            print(f"Error saving progress file: {str(e)}")
    
    # async def scrape_and_save_area(self, area_name: str, area_url: str) -> List[Dict]:
    #     """
    #     Scrape restaurants for a specific area with detailed progress tracking
        
    #     Args:
    #         area_name: Name of the area (in Arabic)
    #         area_url: Talabat URL for the area
        
    #     Returns:
    #         List of restaurant data dictionaries
    #     """
    #     print(f"\n{'='*50}")
    #     print(f"SCRAPING AREA: {area_name}")
    #     print(f"URL: {area_url}")
    #     print(f"{'='*50}\n")
        
    #     # Initialize area results
    #     all_area_results = []
    #     current_progress = self.progress["current_progress"]
        
    #     # Check if we're resuming within this area
    #     is_resuming = current_progress["area_name"] == area_name
    #     start_page = current_progress["current_page"] if is_resuming else 1
    #     start_restaurant = current_progress["current_restaurant"] if is_resuming else 0
        
    #     if is_resuming:
    #         print(f"Resuming area {area_name} from page {current_progress['current_page']} "
    #               f"restaurant {current_progress['current_restaurant']}")
            
    #         # Load processed results from previous run
    #         if os.path.exists(os.path.join(self.output_dir, f"{area_name}_partial.json")):
    #             try:
    #                 with open(os.path.join(self.output_dir, f"{area_name}_partial.json"), 'r', encoding='utf-8') as f:
    #                     all_area_results = json.load(f)
    #                 print(f"Loaded {len(all_area_results)} previously processed restaurants")
    #             except Exception as e:
    #                 print(f"Error loading partial area results: {e}")
    #                 all_area_results = []
    #     else:
    #         # Reset progress for new area
    #         current_progress["area_name"] = area_name
    #         current_progress["current_page"] = start_page
    #         current_progress["total_pages"] = 0
    #         current_progress["current_restaurant"] = start_restaurant
    #         current_progress["total_restaurants"] = 0
    #         current_progress["processed_restaurants"] = []
    #         current_progress["completed_pages"] = []
    #         self.save_progress()
        
    #     skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics", "Grocery, Hypermarket"}
        
    #     # First determine total pages if not already known
    #     if current_progress["total_pages"] == 0:
    #         total_pages = await self.determine_total_pages(area_url)
    #         current_progress["total_pages"] = total_pages
    #         self.save_progress()
    #     else:
    #         total_pages = current_progress["total_pages"]
        
    #     print(f"Total pages for {area_name}: {total_pages}")
        
    #     # Process each page in the area
    #     for page_num in range(start_page, total_pages + 1):
    #         # Skip already completed pages
    #         if page_num < current_progress["current_page"] or page_num in current_progress["completed_pages"]:
    #             print(f"Skipping already completed page {page_num}")
    #             continue
            
    #         # Construct page URL
    #         if page_num == 1:
    #             page_url = area_url
    #         else:
    #             # Check if the base URL already has query parameters
    #             if "?" in area_url:
    #                 # Add page parameter to existing query string
    #                 if "page=" in area_url:
    #                     # Replace existing page parameter
    #                     page_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
    #                 else:
    #                     # Add page parameter
    #                     page_url = f"{area_url}&page={page_num}"
    #             else:
    #                 # Add page parameter as the first query parameter
    #                 page_url = f"{area_url}?page={page_num}"
            
    #         print(f"\n--- Processing Page {page_num}/{total_pages} for {area_name} ---")
    #         current_progress["current_page"] = page_num
    #         self.save_progress()
            
    #         # Retry mechanism for loading restaurant cards
    #         max_retries = 3
    #         for attempt in range(max_retries):
    #             try:
    #                 # Get restaurant listings for this page
    #                 restaurants_on_page = await self.get_page_restaurants(page_url, page_num)
    #                 if not restaurants_on_page:
    #                     raise Exception("No restaurants found")
    #                 print(f"Found {len(restaurants_on_page)} restaurants on page {page_num}")
    #                 break
    #             except Exception as e:
    #                 print(f"Error waiting for restaurant cards on page {page_num}: {e}")
    #                 if attempt < max_retries - 1:
    #                     print(f"Retrying page {page_num} (attempt {attempt + 1}/{max_retries})...")
    #                     await asyncio.sleep(5)  # Wait before retrying
    #                 else:
    #                     print(f"Skipping page {page_num} after {max_retries} failed attempts")
    #                     restaurants_on_page = []
            
    #         # Update total restaurants on page
    #         if current_progress["total_restaurants"] == 0 or page_num > current_progress["current_page"]:
    #             current_progress["total_restaurants"] = len(restaurants_on_page)
    #             current_progress["current_restaurant"] = 0
            
    #         # Process each restaurant on the page
    #         for rest_idx, restaurant in enumerate(restaurants_on_page):
    #             # Skip already processed restaurants on this page
    #             if rest_idx < current_progress["current_restaurant"]:
    #                 print(f"Skipping already processed restaurant {rest_idx+1}/{len(restaurants_on_page)}")
    #                 continue
                
    #             # Set current restaurant position
    #             current_progress["current_restaurant"] = rest_idx + 1  # Increment to the next restaurant
                
    #             # Check if restaurant is in a category we want to skip
    #             if any(category in restaurant['cuisine'] for category in skip_categories):
    #                 print(f"\nSkipping {restaurant['name']} - Category: {restaurant['cuisine']}")
    #                 # Save progress to mark this as processed
    #                 current_progress["processed_restaurants"].append(restaurant["name"])
    #                 self.save_progress()
    #                 print(json.dumps(self.progress, indent=2, ensure_ascii=False))  # Print progress after each restaurant
    #                 continue
                
    #             try:
    #                 print(f"\nProcessing restaurant {rest_idx+1}/{len(restaurants_on_page)} on page {page_num}: {restaurant['name']}")
                    
    #                 # Initialize fields if not already present
    #                 if "menu_items" not in restaurant:
    #                     restaurant['menu_items'] = {}
    #                 if "info" not in restaurant:
    #                     restaurant['info'] = {}
    #                 if "reviews" not in restaurant:
    #                     restaurant['reviews'] = {}
                    
    #                 try:
    #                     # Get menu data
    #                     print(f"Scraping menu for {restaurant['name']}...")
    #                     menu_data = await self.talabat_scraper.get_restaurant_menu(restaurant['url'])
    #                     if menu_data:
    #                         restaurant['menu_items'] = menu_data
    #                     else:
    #                         print(f"Failed to get menu for {restaurant['name']}")
                        
    #                     # Get restaurant info with retry
    #                     info_data = await self.talabat_scraper.get_restaurant_info(restaurant['url'])
    #                     if info_data:
    #                         restaurant['info'] = info_data
                        
    #                     # Get reviews if we have a reviews URL
    #                     if restaurant['info'].get('Reviews URL') and restaurant['info']['Reviews URL'] != 'Not Available':
    #                         print(f"Scraping reviews for {restaurant['name']}...")
    #                         reviews_data = self.talabat_scraper.get_reviews_data(restaurant['info']['Reviews URL'])
    #                         if reviews_data:
    #                             restaurant['reviews'] = reviews_data
                        
    #                 except Exception as e:
    #                     print(f"Error processing restaurant data for {restaurant['name']}: {str(e)}")
                    
    #                 # Add to results
    #                 all_area_results.append(restaurant)
                    
    #                 # Mark this restaurant as processed
    #                 current_progress["processed_restaurants"].append(restaurant["name"])
                    
    #                 # Save progress after processing each restaurant
    #                 self.save_progress()
    #                 print(json.dumps(self.progress, indent=2, ensure_ascii=False))  # Print progress after each restaurant
                    
    #                 # Save partial results after each restaurant
    #                 partial_filename = os.path.join(self.output_dir, f"{area_name}_partial.json")
    #                 with open(partial_filename, 'w', encoding='utf-8') as f:
    #                     json.dump(all_area_results, f, indent=2, ensure_ascii=False)
                    
    #                 # Brief delay between restaurants
    #                 await asyncio.sleep(2)
                    
    #             except Exception as e:
    #                 print(f"Critical error processing restaurant {restaurant['name']}: {str(e)}")
    #                 import traceback
    #                 traceback.print_exc()
    #                 # Still save progress to mark this as attempted
    #                 current_progress["processed_restaurants"].append(restaurant["name"])
                    
    #                 # Save progress after processing each restaurant
    #                 self.save_progress()
    #                 print(json.dumps(self.progress, indent=2, ensure_ascii=False))  # Print progress after each restaurant
            
    #         # Mark page as completed
    #         current_progress["completed_pages"].append(page_num)
    #         current_progress["current_restaurant"] = 0  # Reset for next page
            
    #         # Save progress after finishing each page
    #         self.save_progress()
    #         print("\nProgress after finishing page:")
    #         print(json.dumps(self.progress, indent=2, ensure_ascii=False))
            
    #         # Brief pause between pages
    #         await asyncio.sleep(3)
        
    #     # Save final area results
    #     json_filename = os.path.join(self.output_dir, f"{area_name}.json")
    #     with open(json_filename, 'w', encoding='utf-8') as f:
    #         json.dump(all_area_results, f, indent=2, ensure_ascii=False)
        
    #     # Update all_results in progress
    #     self.progress["all_results"][area_name] = all_area_results
        
    #     # Save progress after finishing the area
    #     self.save_progress()
    #     print("\nProgress after finishing area:")
    #     print(json.dumps(self.progress, indent=2, ensure_ascii=False))
        
    #     # Clean up partial file
    #     partial_filename = os.path.join(self.output_dir, f"{area_name}_partial.json")
    #     if os.path.exists(partial_filename):
    #         try:
    #             os.remove(partial_filename)
    #         except Exception as e:
    #             print(f"Warning: Could not remove partial file: {e}")
        
    #     # Create Excel workbook for the area
    #     workbook = Workbook()
    #     sheet_name = area_name
    #     self.create_excel_sheet(workbook, sheet_name, all_area_results)
        
    #     # Save the Excel file
    #     excel_filename = os.path.join(self.output_dir, f"{area_name}.xlsx")
    #     workbook.save(excel_filename)
    #     print(f"Excel file saved: {excel_filename}")
        
    #     # Upload the Excel file to Google Drive
    #     upload_success = self.upload_to_drive(excel_filename)
    #     if upload_success:
    #         print(f"Successfully uploaded {excel_filename} to Google Drive")
    #     else:
    #         print(f"Failed to upload {excel_filename} to Google Drive")
        
    #     # Reset current progress for next area
    #     current_progress["area_name"] = None
    #     current_progress["current_page"] = 0
    #     current_progress["total_pages"] = 0
    #     current_progress["current_restaurant"] = 0
    #     current_progress["total_restaurants"] = 0
    #     current_progress["processed_restaurants"] = []
    #     current_progress["completed_pages"] = []
        
    #     # Save progress after resetting for next area
    #     self.save_progress()
    #     print("\nProgress after resetting for next area:")
    #     print(json.dumps(self.progress, indent=2, ensure_ascii=False))
        
    #     print(f"Saved {len(all_area_results)} restaurants for {area_name} to {json_filename}")
    #     return all_area_results

    async def scrape_and_save_area(self, area_name: str, area_url: str, start_page: int = 141, start_restaurant: int = 7) -> List[Dict]:
        """
        Scrape restaurants for a specific area with detailed progress tracking
        
        Args:
            area_name: Name of the area (in Arabic)
            area_url: Talabat URL for the area
            start_page: Page number to start scraping from
            start_restaurant: Restaurant number to start scraping from on the first page
        
        Returns:
            List of restaurant data dictionaries
        """
        print(f"\n{'='*50}")
        print(f"SCRAPING AREA: {area_name}")
        print(f"URL: {area_url}")
        print(f"{'='*50}\n")
        
        # Initialize area results
        all_area_results = []
        current_progress = self.progress["current_progress"]
        
        # Check if we're resuming within this area
        is_resuming = current_progress["area_name"] == area_name
        
        if is_resuming:
            print(f"Resuming area {area_name} from page {current_progress['current_page']} "
                  f"restaurant {current_progress['current_restaurant']}")
            
            # Load processed results from previous run
            if os.path.exists(os.path.join(self.output_dir, f"{area_name}_partial.json")):
                try:
                    with open(os.path.join(self.output_dir, f"{area_name}_partial.json"), 'r', encoding='utf-8') as f:
                        all_area_results = json.load(f)
                    print(f"Loaded {len(all_area_results)} previously processed restaurants")
                except Exception as e:
                    print(f"Error loading partial area results: {e}")
                    all_area_results = []
        else:
            # Reset progress for new area
            current_progress["area_name"] = area_name
            current_progress["current_page"] = start_page
            current_progress["total_pages"] = 0
            current_progress["current_restaurant"] = start_restaurant - 1
            current_progress["total_restaurants"] = 0
            current_progress["processed_restaurants"] = []
            current_progress["completed_pages"] = []
            self.save_progress()
        
        skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics", "Grocery, Hypermarket"}
        
        # First determine total pages if not already known
        if current_progress["total_pages"] == 0:
            total_pages = await self.determine_total_pages(area_url)
            current_progress["total_pages"] = total_pages
            self.save_progress()
        else:
            total_pages = current_progress["total_pages"]
        
        print(f"Total pages for {area_name}: {total_pages}")
        
        # Process each page in the area
        for page_num in range(start_page, total_pages + 1):
            # Skip already completed pages
            if page_num < current_progress["current_page"] or page_num in current_progress["completed_pages"]:
                print(f"Skipping already completed page {page_num}")
                continue
            
            # Construct page URL
            if page_num == 1:
                page_url = area_url
            else:
                # Check if the base URL already has query parameters
                if "?" in area_url:
                    # Add page parameter to existing query string
                    if "page=" in area_url:
                        # Replace existing page parameter
                        page_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
                    else:
                        # Add page parameter
                        page_url = f"{area_url}&page={page_num}"
                else:
                    # Add page parameter as the first query parameter
                    page_url = f"{area_url}?page={page_num}"
            
            print(f"\n--- Processing Page {page_num}/{total_pages} for {area_name} ---")
            current_progress["current_page"] = page_num
            self.save_progress()
            
            # Get restaurant listings for this page
            restaurants_on_page = await self.get_page_restaurants(page_url, page_num)
            print(f"Found {len(restaurants_on_page)} restaurants on page {page_num}")
            
            # Update total restaurants on page
            if current_progress["current_restaurant"] == 0 or page_num > current_progress["current_page"]:
                current_progress["total_restaurants"] = len(restaurants_on_page)
                current_progress["current_restaurant"] = 0
            
            # Process each restaurant on the page
            for rest_idx, restaurant in enumerate(restaurants_on_page):
                # Skip already processed restaurants on this page
                if rest_idx < current_progress["current_restaurant"]:
                    print(f"Skipping already processed restaurant {rest_idx+1}/{len(restaurants_on_page)}")
                    continue
                
                # Set current restaurant position
                current_progress["current_restaurant"] = rest_idx
                
                # Check if restaurant is in a category we want to skip
                if any(category in restaurant['cuisine'] for category in skip_categories):
                    print(f"\nSkipping {restaurant['name']} - Category: {restaurant['cuisine']}")
                    # Save progress to mark this as processed
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
                    continue
                
                try:
                    print(f"\nProcessing restaurant {rest_idx+1}/{len(restaurants_on_page)} on page {page_num}: {restaurant['name']}")
                    
                    # Initialize fields if not already present
                    if "menu_items" not in restaurant:
                        restaurant['menu_items'] = {}
                    if "info" not in restaurant:
                        restaurant['info'] = {}
                    if "reviews" not in restaurant:
                        restaurant['reviews'] = {}
                    
                    try:
                        # Get menu data
                        print(f"Scraping menu for {restaurant['name']}...")
                        menu_data = await self.talabat_scraper.get_restaurant_menu(restaurant['url'])
                        if menu_data:
                            restaurant['menu_items'] = menu_data
                        else:
                            print(f"Failed to get menu for {restaurant['name']}")
                        
                        # Get restaurant info with retry
                        info_data = await self.talabat_scraper.get_restaurant_info(restaurant['url'])
                        if info_data:
                            restaurant['info'] = info_data
                        
                        # Get reviews if we have a reviews URL
                        if restaurant['info'].get('Reviews URL') and restaurant['info']['Reviews URL'] != 'Not Available':
                            print(f"Scraping reviews for {restaurant['name']}...")
                            reviews_data = self.talabat_scraper.get_reviews_data(restaurant['info']['Reviews URL'])
                            if reviews_data:
                                restaurant['reviews'] = reviews_data
                        
                    except Exception as e:
                        print(f"Error processing restaurant data for {restaurant['name']}: {str(e)}")
                    
                    # Add to results
                    all_area_results.append(restaurant)
                    
                    # Mark this restaurant as processed
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
                    
                    # Save partial results after each restaurant
                    partial_filename = os.path.join(self.output_dir, f"{area_name}_partial.json")
                    with open(partial_filename, 'w', encoding='utf-8') as f:
                        json.dump(all_area_results, f, indent=2, ensure_ascii=False)
                    
                    # Brief delay between restaurants
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    print(f"Critical error processing restaurant {restaurant['name']}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Still save progress to mark this as attempted
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
            
            # Mark page as completed
            current_progress["completed_pages"].append(page_num)
            current_progress["current_restaurant"] = 0  # Reset for next page
            self.save_progress()
            
            # Print progress after finishing each page
            print("\nProgress after finishing page:")
            print(json.dumps(self.progress, indent=2, ensure_ascii=False))
            
            # Brief pause between pages
            await asyncio.sleep(3)
        
        # Save final area results
        json_filename = os.path.join(self.output_dir, f"{area_name}.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(all_area_results, f, indent=2, ensure_ascii=False)
        
        # Update all_results in progress
        self.progress["all_results"][area_name] = all_area_results
        self.save_progress()
        
        # Clean up partial file
        partial_filename = os.path.join(self.output_dir, f"{area_name}_partial.json")
        if os.path.exists(partial_filename):
            try:
                os.remove(partial_filename)
            except Exception as e:
                print(f"Warning: Could not remove partial file: {e}")
        
        # Reset current progress for next area
        current_progress["area_name"] = None
        current_progress["current_page"] = 0
        current_progress["total_pages"] = 0
        current_progress["current_restaurant"] = 0
        current_progress["total_restaurants"] = 0
        current_progress["processed_restaurants"] = []
        current_progress["completed_pages"] = []
        self.save_progress()
        
        # Print progress after finishing each area
        print("\nProgress after finishing area:")
        print(json.dumps(self.progress, indent=2, ensure_ascii=False))
        
        print(f"Saved {len(all_area_results)} restaurants for {area_name} to {json_filename}")
        return all_area_results
    
    async def determine_total_pages(self, area_url: str) -> int:
        """Determine the total number of pages for an area"""
        print(f"Determining total pages for URL: {area_url}")
        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                page = await context.new_page()
                page.set_default_timeout(120000)  # Increase timeout to 120 seconds
                
                response = await page.goto(area_url, wait_until='domcontentloaded')
                if not response or not response.ok:
                    print(f"Failed to load page: {response.status if response else 'No response'}")
                    return 1
                
                # Wait for content to load
                try:
                    await page.wait_for_selector("ul[data-test='pagination'], .vendor-card, [data-testid='restaurant-a']", timeout=30000)
                except Exception as e:
                    print(f"Error waiting for content: {e}")
                    return 1
                
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
                        print("Could not detect pagination, assuming single page")
                except Exception as e:
                    print(f"Error detecting pagination: {e}, defaulting to single page")
                    last_page = 1
                
                await browser.close()
                return last_page
        except Exception as e:
            print(f"Error determining total pages: {e}")
            return 1
    
    async def get_page_restaurants(self, page_url: str, page_num: int) -> List[Dict]:
        """Gets the restaurant listings from a specific page"""
        browser = None
        restaurants = []
        
        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                page = await context.new_page()
                page.set_default_timeout(120000)  # Increase timeout to 120 seconds
                
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
                
                # Extract restaurants from page
                restaurants = await self.talabat_scraper._extract_restaurants_from_page(page, page_num)
        
        except Exception as e:
            print(f"Critical error getting page restaurants: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            if browser:
                await browser.close()
        
        return restaurants
    
    def create_excel_sheet(self, workbook, sheet_name: str, data: List[Dict]):
        """
        Create a sheet in the Excel workbook for the specified area data
        
        Args:
            workbook: Excel workbook to add sheet to
            sheet_name: Name of the sheet (area name in Arabic)
            data: List of restaurant data dictionaries
        """
        # Create sheet
        sheet = workbook.create_sheet(title=sheet_name)
        
        # Extract key information for the Excel file
        simplified_data = []
        for restaurant in data:
            # Basic information
            restaurant_info = {
                "Name": restaurant.get("name", ""),
                "Cuisine": restaurant.get("cuisine", ""),
                "Rating": restaurant.get("rating", ""),
                "Delivery Time": restaurant.get("delivery_time", ""),
                "Delivery Fee": restaurant.get("delivery_fee", ""),
                "Min Order": restaurant.get("min_order", ""),
                "URL": restaurant.get("url", ""),
            }
            
            # Add info from restaurant details if available
            if restaurant.get("info"):
                restaurant_info.update({
                    "Address": restaurant["info"].get("Address", ""),
                    "Working Hours": restaurant["info"].get("Working Hours", ""),
                })
            
            # Add rating from reviews if available
            if restaurant.get("reviews") and restaurant["reviews"].get("Rating_value"):
                restaurant_info["Rating Value"] = restaurant["reviews"]["Rating_value"]
                restaurant_info["Ratings Count"] = restaurant["reviews"].get("Ratings_count", "")
                restaurant_info["Reviews Count"] = restaurant["reviews"].get("Reviews_count", "")
            
            # Count menu categories and items
            if restaurant.get("menu_items"):
                restaurant_info["Menu Categories"] = len(restaurant["menu_items"])
                item_count = sum(len(items) for items in restaurant["menu_items"].values())
                restaurant_info["Menu Items"] = item_count
            
            simplified_data.append(restaurant_info)
        
        # Create DataFrame
        if simplified_data:
            df = pd.DataFrame(simplified_data)
            
            # Write data to sheet
            for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
                for c_idx, value in enumerate(row, 1):
                    sheet.cell(row=r_idx, column=c_idx, value=value)
            
            # Auto-adjust column widths
            for column in sheet.columns:
                max_length = 0
                column_letter = get_column_letter(column[0].column)
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                sheet.column_dimensions[column_letter].width = min(adjusted_width, 50)
        else:
            sheet.cell(row=1, column=1, value="No data found for this area")
    
    def upload_to_drive(self, file_path):
        """
        Upload Excel file to Google Drive folders
        
        Args:
            file_path: Path to the Excel file to upload
            
        Returns:
            bool: True if upload successful, False otherwise
        """
        print(f"\nUploading {file_path} to Google Drive...")
        
        try:
            # Authenticate with Google Drive
            if not self.drive_uploader.authenticate():
                print("Failed to authenticate with Google Drive")
                return False
            
            # Upload the file to both folders
            file_ids = self.drive_uploader.upload_to_multiple_folders(file_path)
            
            if len(file_ids) == 2:
                print(f"Successfully uploaded file to both Google Drive folders")
                print(f"File IDs: {file_ids}")
                return True
            else:
                print(f"Partially uploaded file to {len(file_ids)} out of 2 folders")
                return False
                
        except Exception as e:
            print(f"Error uploading to Google Drive: {str(e)}")
            return False
    
    async def run(self):
        """Main execution function to scrape all areas with enhanced resume capability."""
        import re  # Import needed for regex operations
        
        # Define governorate and its areas with their URLs
        ahmadi_areas = [
            # Area Name, URL
            ("الظهر", "https://www.talabat.com/kuwait/restaurants/59/dhaher"),
            ("الرقه", "https://www.talabat.com/kuwait/restaurants/37/riqqa"),
            # ("هدية", "https://www.talabat.com/kuwait/restaurants/30/hadiya"),
            # ("المنقف", "https://www.talabat.com/kuwait/restaurants/32/mangaf"),
            # ("أبو حليفة", "https://www.talabat.com/kuwait/restaurants/2/abu-halifa"),
            # ("الفنطاس", "https://www.talabat.com/kuwait/restaurants/38/fintas"),
            # ("العقيلة", "https://www.talabat.com/kuwait/restaurants/79/egaila"),
            # ("الصباحية", "https://www.talabat.com/kuwait/restaurants/31/sabahiya"),
            # ("الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
            # ("الفحيحيل", "https://www.talabat.com/kuwait/restaurants/5/fahaheel"),
            # ("شرق الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
            # ("ضاحية علي صباح السالم", "https://www.talabat.com/kuwait/restaurants/82/ali-sabah-al-salem-umm-al-hayman"),
            # ("ميناء عبد الله", "https://www.talabat.com/kuwait/restaurants/100/mina-abdullah"),
            # ("بنيدر", "https://www.talabat.com/kuwait/restaurants/6650/bnaider"),
            # ("الزور", "https://www.talabat.com/kuwait/restaurants/2053/zour"),
            # ("الجليعة", "https://www.talabat.com/kuwait/restaurants/6860/al-julaiaa"),
            # ("المهبولة", "https://www.talabat.com/kuwait/restaurants/24/mahboula"),
            # ("النويصيب", "https://www.talabat.com/kuwait/restaurants/2054/nuwaiseeb"),
            # ("الخيران", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
            # ("الوفرة", "https://www.talabat.com/kuwait/restaurants/2057/wafra-farms"),
            # ("ضاحية فهد الأحمد", "https://www.talabat.com/kuwait/restaurants/98/fahad-al-ahmed"),
            # ("ضاحية جابر العلي", "https://www.talabat.com/kuwait/restaurants/60/jaber-al-ali"),
            # ("مدينة صباح الأحمد السكنية", "https://www.talabat.com/kuwait/restaurants/6931/sabah-al-ahmad-2"),
            # ("مدينة صباح الأحمد البحرية", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
            # ("ميناء الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi")
        ]
        
        # Create an Excel workbook for the governorate or load existing
        excel_filename = os.path.join(self.output_dir, "الاحمدي.xlsx")
        
        # Initialize workbook
        workbook = Workbook()
        if "Sheet" in workbook.sheetnames:
            workbook.remove(workbook["Sheet"])
        
        # Track all results for the combined JSON
        all_results = self.progress.get("all_results", {})
        
        # Get already completed areas
        completed_areas = self.progress.get("completed_areas", [])
        current_area_index = self.progress.get("current_area_index", 0)
        
        print(f"Starting from area index {current_area_index}")
        print(f"Already completed areas: {', '.join(completed_areas) if completed_areas else 'None'}")
        
        # Check if we're resuming mid-area
        current_progress = self.progress["current_progress"]
        resuming_area = current_progress.get("area_name")
        
        # Special handling for resume mid-area
        if resuming_area:
            # Find the area index
            for idx, (area_name, _) in enumerate(ahmadi_areas):
                if area_name == resuming_area:
                    print(f"Resuming from area {resuming_area} (index {idx})")
                    current_area_index = idx
                    self.progress["current_area_index"] = idx
                    self.save_progress()
                    break
        
        # Process each area in the governorate
        for idx, (area_name, area_url) in enumerate(ahmadi_areas):
            # Skip already completed areas
            if area_name in completed_areas and area_name != resuming_area:
                print(f"Skipping already processed area: {area_name}")
                continue
            
            # Skip areas before the current index
            if idx < current_area_index:
                print(f"Skipping area {area_name} (index {idx} < current index {current_area_index})")
                continue
            
            try:
                # Update current area index
                self.progress["current_area_index"] = idx
                self.save_progress()
                
                # Scrape area data and save to JSON
                area_results = await self.scrape_and_save_area(area_name, area_url)
                
                # Add to all results
                all_results[area_name] = area_results
                self.progress["all_results"] = all_results
                
                # Create Excel sheet for this area
                self.create_excel_sheet(workbook, area_name, area_results)
                
                # Save progress after each area
                workbook.save(excel_filename)
                print(f"Updated Excel file: {excel_filename}")
                
                # Mark as completed
                if area_name not in completed_areas:
                    completed_areas.append(area_name)
                    self.progress["completed_areas"] = completed_areas
                
                # Save progress
                self.save_progress()
                
                # Brief pause between areas
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"Error processing area {area_name}: {str(e)}")
                import traceback
                traceback.print_exc()
                self.save_progress()  # Save progress even after error
        
        # Save the final Excel file
        workbook.save(excel_filename)
        
        # Save combined results to a single JSON file
        combined_json_filename = os.path.join(self.output_dir, "الاحمدي_all.json")
        with open(combined_json_filename, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
            
        print(f"\n{'='*50}")
        print(f"SCRAPING COMPLETED")
        print(f"Excel file saved: {excel_filename}")
        print(f"Combined JSON saved: {combined_json_filename}")
        
        # Upload Excel to Google Drive if all areas are completed
        if len(completed_areas) == len(ahmadi_areas):
            excel_file_path = os.path.join(os.getcwd(), excel_filename)
            upload_success = self.upload_to_drive(excel_file_path)
            
            if upload_success:
                print(f"Successfully uploaded Excel file to Google Drive")
            else:
                print(f"Failed to upload Excel file to Google Drive")
        else:
            print(f"Scraping incomplete ({len(completed_areas)}/{len(ahmadi_areas)} areas). Skipping upload to Drive.")
            
        print(f"{'='*50}\n")


def create_credentials_file():
    """Create the credentials.json file from environment variable."""
    try:
        # Get credentials from environment variable
        credentials_json = os.environ.get('TALABAT_GCLOUD_KEY_JSON')
        
        if not credentials_json:
            print("ERROR: TALABAT_GCLOUD_KEY_JSON environment variable not found!")
            print("Please set the TALABAT_GCLOUD_KEY_JSON environment variable with the Google service account credentials")
            return False
        
        # Write credentials to file
        with open('credentials.json', 'w') as f:
            f.write(credentials_json)
        
        print("Successfully created credentials.json from environment variable")
        return True
    
    except Exception as e:
        print(f"ERROR: Failed to create credentials.json: {str(e)}")
        return False


async def main():
    """Entry point for the application."""
    # Create credentials file from environment variable
    if not create_credentials_file():
        print("Could not create credentials.json from environment variable")
        sys.exit(1)
        
    # Check if credentials file exists
    if not os.path.exists('credentials.json'):
        print("ERROR: credentials.json not found!")
        print("Please create a service account in Google Cloud Console and download the credentials")
        print("Save the file as 'credentials.json' in the same directory as this script")
        sys.exit(1)
    
    try:
        # Initialize and run the scraper
        scraper = MainScraper()
        await scraper.run()
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Saving progress before exit...")
        if 'scraper' in locals():
            scraper.save_progress()
        print("Progress saved. Exiting.")
    except Exception as e:
        print(f"Critical error in main execution: {e}")
        import traceback
        traceback.print_exc()
        if 'scraper' in locals():
            scraper.save_progress()
        sys.exit(1)


if __name__ == "__main__":
    scraper = MainScraper()
    scraper.print_progress_details()  # Print the progress details
    asyncio.run(scraper.run())
    
