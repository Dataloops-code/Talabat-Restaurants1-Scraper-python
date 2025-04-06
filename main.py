import asyncio
import json
import os
import tempfile
import sys
import subprocess
import re
from typing import Dict, List, Tuple
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter
from playwright.async_api import async_playwright
from talabat_main_scraper import TalabatScraper
from SavingOnDrive import SavingOnDrive
from time import sleep
from datetime import datetime

class MainScraper:
    PROGRESS_FILE = "progress.json"
    DATA_FILE = "scraped_data.json"

    def __init__(self):
        self.talabat_scraper = TalabatScraper()
        self.output_dir = "output"
        self.drive_uploader = SavingOnDrive('credentials.json')
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load progress and data
        self.progress = self.load_progress()
        self.scraped_data = self.load_scraped_data()
        
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
        """Load progress from progress.json or return default structure"""
        if os.path.exists(self.PROGRESS_FILE):
            try:
                with open(self.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                print(f"Loaded progress from {self.PROGRESS_FILE}")
                return progress
            except Exception as e:
                print(f"Error loading progress file: {e}")
                print("Creating new progress file...")
        
        # Default progress structure
        default_progress = {
            "completed_areas": [],
            "current_area_index": 0,
            "last_updated": None,
            "all_results": {},  # Will reference scraped_data.json
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
        self.save_progress(default_progress)
        return default_progress

    def save_progress(self, progress: Dict = None):
        """Save current progress to progress.json with timestamp"""
        if progress is None:
            progress = self.progress
        try:
            progress["last_updated"] = datetime.now().isoformat()
            with tempfile.NamedTemporaryFile('w', delete=False, dir='.') as temp_file:
                json.dump(progress, temp_file, indent=2, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_filename = temp_file.name
            os.replace(temp_filename, self.PROGRESS_FILE)
            print(f"Saved progress to {self.PROGRESS_FILE}")
        except Exception as e:
            print(f"Error saving progress file: {e}")

    def load_scraped_data(self) -> Dict:
        """Load scraped data from scraped_data.json or return empty dict"""
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print(f"Loaded scraped data from {self.DATA_FILE}")
                return data
            except Exception as e:
                print(f"Error loading scraped data file: {e}")
                print("Creating new scraped data file...")
        
        # Default empty data
        default_data = {}
        self.save_scraped_data(default_data)
        return default_data

    def save_scraped_data(self, data: Dict = None):
        """Save scraped data to scraped_data.json"""
        if data is None:
            data = self.scraped_data
        try:
            with tempfile.NamedTemporaryFile('w', delete=False, dir='.') as temp_file:
                json.dump(data, temp_file, indent=2, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_filename = temp_file.name
            os.replace(temp_filename, self.DATA_FILE)
            print(f"Saved scraped data to {self.DATA_FILE}")
        except Exception as e:
            print(f"Error saving scraped data file: {e}")

    def print_progress_details(self):
        """Print the details of progress including all results and each restaurant scraped"""
        try:
            with open(self.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            print("\nProgress Details:")
            print(json.dumps(progress, indent=2, ensure_ascii=False))

            with open(self.DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print("\nScraped Data:")
            for area, results in data.items():
                print(f"\nArea: {area}")
                for restaurant in results:
                    print(json.dumps(restaurant, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Error reading progress or data file: {str(e)}")

    async def scrape_and_save_area(self, area_name: str, area_url: str) -> List[Dict]:
        """Scrape restaurants for a specific area with detailed progress tracking"""
        print(f"\n{'='*50}")
        print(f"SCRAPING AREA: {area_name}")
        print(f"URL: {area_url}")
        print(f"{'='*50}\n")
        
        all_area_results = self.scraped_data.get(area_name, [])
        current_progress = self.progress["current_progress"]
        
        # Check if we're resuming within this area
        is_resuming = current_progress["area_name"] == area_name
        start_page = current_progress["current_page"] if is_resuming else 1
        start_restaurant = current_progress["current_restaurant"] if is_resuming else 0
        
        if is_resuming:
            print(f"Resuming area {area_name} from page {start_page} restaurant {start_restaurant}")
        else:
            # Reset progress for new area
            current_progress["area_name"] = area_name
            current_progress["current_page"] = start_page
            current_progress["total_pages"] = 0
            current_progress["current_restaurant"] = start_restaurant
            current_progress["total_restaurants"] = 0
            current_progress["processed_restaurants"] = []
            current_progress["completed_pages"] = []
            self.save_progress()
        
        skip_categories = {"Grocery, Convenience Store", "Pharmacy", "Flowers", "Electronics", "Grocery, Hypermarket"}
        
        # Determine total pages if not already known
        if current_progress["total_pages"] == 0:
            total_pages = await self.determine_total_pages(area_url)
            current_progress["total_pages"] = total_pages
            self.save_progress()
        else:
            total_pages = current_progress["total_pages"]
        
        print(f"Total pages for {area_name}: {total_pages}")
        
        # Process each page in the area
        for page_num in range(start_page, total_pages + 1):
            if page_num in current_progress["completed_pages"]:
                print(f"Skipping already completed page {page_num}")
                continue
            
            # Construct page URL
            if page_num == 1:
                page_url = area_url
            else:
                if "?" in area_url:
                    if "page=" in area_url:
                        page_url = re.sub(r'page=\d+', f'page={page_num}', area_url)
                    else:
                        page_url = f"{area_url}&page={page_num}"
                else:
                    page_url = f"{area_url}?page={page_num}"
            
            print(f"\n--- Processing Page {page_num}/{total_pages} for {area_name} ---")
            current_progress["current_page"] = page_num
            self.save_progress()
            
            # Get restaurants with retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    restaurants_on_page = await self.get_page_restaurants(page_url, page_num)
                    if not restaurants_on_page:
                        raise Exception("No restaurants found")
                    print(f"Found {len(restaurants_on_page)} restaurants on page {page_num}")
                    break
                except Exception as e:
                    print(f"Error on page {page_num}: {e}")
                    if attempt < max_retries - 1:
                        print(f"Retrying page {page_num} (attempt {attempt + 1}/{max_retries})...")
                        await asyncio.sleep(5)
                    else:
                        print(f"Skipping page {page_num} after {max_retries} failed attempts")
                        restaurants_on_page = []
            
            # Update total restaurants
            if current_progress["total_restaurants"] == 0 or page_num > start_page:
                current_progress["total_restaurants"] = len(restaurants_on_page)
                if not is_resuming or page_num > start_page:
                    current_progress["current_restaurant"] = 0
            
            # Process each restaurant
            for rest_idx, restaurant in enumerate(restaurants_on_page):
                if rest_idx < current_progress["current_restaurant"]:
                    print(f"Skipping already processed restaurant {rest_idx+1}/{len(restaurants_on_page)}")
                    continue
                
                current_progress["current_restaurant"] = rest_idx
                
                if any(category in restaurant['cuisine'] for category in skip_categories):
                    print(f"\nSkipping {restaurant['name']} - Category: {restaurant['cuisine']}")
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
                    continue
                
                print(f"\nProcessing restaurant {rest_idx+1}/{len(restaurants_on_page)} on page {page_num}: {restaurant['name']}")
                
                try:
                    restaurant.setdefault("menu_items", {})
                    restaurant.setdefault("info", {})
                    restaurant.setdefault("reviews", {})
                    
                    menu_data = await self.talabat_scraper.get_restaurant_menu(restaurant['url'])
                    if menu_data:
                        restaurant['menu_items'] = menu_data
                    
                    info_data = await self.talabat_scraper.get_restaurant_info(restaurant['url'])
                    if info_data:
                        restaurant['info'] = info_data
                    
                    if restaurant['info'].get('Reviews URL') and restaurant['info']['Reviews URL'] != 'Not Available':
                        reviews_data = self.talabat_scraper.get_reviews_data(restaurant['info']['Reviews URL'])
                        if reviews_data:
                            restaurant['reviews'] = reviews_data
                    
                    all_area_results.append(restaurant)
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
                    
                    # Update scraped data
                    self.scraped_data[area_name] = all_area_results
                    self.save_scraped_data()
                    
                    await asyncio.sleep(2)
                
                except Exception as e:
                    print(f"Error processing restaurant {restaurant['name']}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    current_progress["processed_restaurants"].append(restaurant["name"])
                    self.save_progress()
            
            # Mark page as completed
            current_progress["completed_pages"].append(page_num)
            current_progress["current_restaurant"] = 0
            self.save_progress()
            print("\nProgress after page:")
            print(json.dumps(self.progress, indent=2, ensure_ascii=False))
            await asyncio.sleep(3)
        
        # Save final area results
        json_filename = os.path.join(self.output_dir, f"{area_name}.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(all_area_results, f, indent=2, ensure_ascii=False)
        
        self.progress["all_results"][area_name] = len(all_area_results)  # Store count instead of full data
        self.save_progress()
        
        # Clean up partial file
        partial_filename = os.path.join(self.output_dir, f"{area_name}_partial.json")
        if os.path.exists(partial_filename):
            try:
                os.remove(partial_filename)
            except Exception as e:
                print(f"Warning: Could not remove partial file: {e}")
        
        # Create and save Excel
        workbook = Workbook()
        self.create_excel_sheet(workbook, area_name, all_area_results)
        excel_filename = os.path.join(self.output_dir, f"{area_name}.xlsx")
        workbook.save(excel_filename)
        print(f"Excel file saved: {excel_filename}")
        
        # Upload to Google Drive
        if self.upload_to_drive(excel_filename):
            print(f"Successfully uploaded {excel_filename} to Google Drive")
        else:
            print(f"Failed to upload {excel_filename} to Google Drive")
        
        # Reset current progress
        current_progress["area_name"] = None
        current_progress["current_page"] = 0
        current_progress["total_pages"] = 0
        current_progress["current_restaurant"] = 0
        current_progress["total_restaurants"] = 0
        current_progress["processed_restaurants"] = []
        current_progress["completed_pages"] = []
        self.save_progress()
        
        print(f"Saved {len(all_area_results)} restaurants for {area_name}")
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
                page.set_default_timeout(120000)
                
                response = await page.goto(area_url, wait_until='domcontentloaded')
                if not response or not response.ok:
                    print(f"Failed to load page: {response.status if response else 'No response'}")
                    return 1
                
                await page.wait_for_selector("ul[data-test='pagination'], .vendor-card, [data-testid='restaurant-a']", timeout=30000)
                
                last_page = 1
                pagination = await page.query_selector("ul[data-test='pagination']")
                if pagination:
                    items = await pagination.query_selector_all("li[data-testid='paginate-link']")
                    if items and len(items) > 1:
                        last_page_item = items[-2]
                        last_page_link = await last_page_item.query_selector("a[page]")
                        if last_page_link:
                            last_page_attr = await last_page_link.get_attribute("page")
                            if last_page_attr and last_page_attr.isdigit():
                                last_page = int(last_page_attr)
                
                await browser.close()
                return last_page
        except Exception as e:
            print(f"Error determining total pages: {e}")
            return 1

    async def get_page_restaurants(self, page_url: str, page_num: int) -> List[Dict]:
        """Gets the restaurant listings from a specific page"""
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.firefox.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                page = await context.new_page()
                page.set_default_timeout(120000)
                
                response = await page.goto(page_url, wait_until='domcontentloaded')
                if not response or not response.ok:
                    print(f"Failed to load page {page_num}: {response.status if response else 'No response'}")
                    return []
                
                await page.wait_for_selector(".vendor-card, [data-testid='restaurant-a']", timeout=30000)
                return await self.talabat_scraper._extract_restaurants_from_page(page, page_num)
        except Exception as e:
            print(f"Error getting page restaurants: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            if browser:
                await browser.close()

    def create_excel_sheet(self, workbook, sheet_name: str, data: List[Dict]):
        """Create a sheet in the Excel workbook for the specified area data"""
        sheet = workbook.create_sheet(title=sheet_name)
        simplified_data = []
        for restaurant in data:
            restaurant_info = {
                "Name": restaurant.get("name", ""),
                "Cuisine": restaurant.get("cuisine", ""),
                "Rating": restaurant.get("rating", ""),
                "Delivery Time": restaurant.get("delivery_time", ""),
                "Delivery Fee": restaurant.get("delivery_fee", ""),
                "Min Order": restaurant.get("min_order", ""),
                "URL": restaurant.get("url", ""),
            }
            if restaurant.get("info"):
                restaurant_info.update({
                    "Address": restaurant["info"].get("Address", ""),
                    "Working Hours": restaurant["info"].get("Working Hours", ""),
                })
            if restaurant.get("reviews") and restaurant["reviews"].get("Rating_value"):
                restaurant_info.update({
                    "Rating Value": restaurant["reviews"]["Rating_value"],
                    "Ratings Count": restaurant["reviews"].get("Ratings_count", ""),
                    "Reviews Count": restaurant["reviews"].get("Reviews_count", ""),
                })
            if restaurant.get("menu_items"):
                restaurant_info["Menu Categories"] = len(restaurant["menu_items"])
                item_count = sum(len(items) for items in restaurant["menu_items"].values())
                restaurant_info["Menu Items"] = item_count
            simplified_data.append(restaurant_info)
        
        if simplified_data:
            df = pd.DataFrame(simplified_data)
            for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
                for c_idx, value in enumerate(row, 1):
                    sheet.cell(row=r_idx, column=c_idx, value=value)
            for column in sheet.columns:
                max_length = max(len(str(cell.value or "")) for cell in column)
                column_letter = get_column_letter(column[0].column)
                sheet.column_dimensions[column_letter].width = min(max_length + 2, 50)
        else:
            sheet.cell(row=1, column=1, value="No data found for this area")

    def upload_to_drive(self, file_path):
        """Upload Excel file to Google Drive folders"""
        print(f"\nUploading {file_path} to Google Drive...")
        try:
            if not self.drive_uploader.authenticate():
                print("Failed to authenticate with Google Drive")
                return False
            file_ids = self.drive_uploader.upload_to_multiple_folders(file_path)
            return len(file_ids) == 2
        except Exception as e:
            print(f"Error uploading to Google Drive: {str(e)}")
            return False

    async def run(self):
        """Main execution function to scrape all areas"""
        ahmadi_areas = [
            ("الظهر", "https://www.talabat.com/kuwait/restaurants/59/dhaher"),
            ("الرقه", "https://www.talabat.com/kuwait/restaurants/37/riqqa"),
            ("هدية", "https://www.talabat.com/kuwait/restaurants/30/hadiya"),
            ("المنقف", "https://www.talabat.com/kuwait/restaurants/32/mangaf"),
            ("أبو حليفة", "https://www.talabat.com/kuwait/restaurants/2/abu-halifa"),
            ("الفنطاس", "https://www.talabat.com/kuwait/restaurants/38/fintas"),
            ("العقيلة", "https://www.talabat.com/kuwait/restaurants/79/egaila"),
            ("الصباحية", "https://www.talabat.com/kuwait/restaurants/31/sabahiya"),
            ("الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
            ("الفحيحيل", "https://www.talabat.com/kuwait/restaurants/5/fahaheel"),
            ("شرق الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
            ("ضاحية علي صباح السالم", "https://www.talabat.com/kuwait/restaurants/82/ali-sabah-al-salem-umm-al-hayman"),
            ("ميناء عبد الله", "https://www.talabat.com/kuwait/restaurants/100/mina-abdullah"),
            ("بنيدر", "https://www.talabat.com/kuwait/restaurants/6650/bnaider"),
            ("الزور", "https://www.talabat.com/kuwait/restaurants/2053/zour"),
            ("الجليعة", "https://www.talabat.com/kuwait/restaurants/6860/al-julaiaa"),
            ("المهبولة", "https://www.talabat.com/kuwait/restaurants/24/mahboula"),
            ("النويصيب", "https://www.talabat.com/kuwait/restaurants/2054/nuwaiseeb"),
            ("الخيران", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
            ("الوفرة", "https://www.talabat.com/kuwait/restaurants/2057/wafra-farms"),
            ("ضاحية فهد الأحمد", "https://www.talabat.com/kuwait/restaurants/98/fahad-al-ahmed"),
            ("ضاحية جابر العلي", "https://www.talabat.com/kuwait/restaurants/60/jaber-al-ali"),
            ("مدينة صباح الأحمد السكنية", "https://www.talabat.com/kuwait/restaurants/6931/sabah-al-ahmad-2"),
            ("مدينة صباح الأحمد البحرية", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
            ("ميناء الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi")
        ]
        
        excel_filename = os.path.join(self.output_dir, "الاحمدي.xlsx")
        workbook = Workbook()
        if "Sheet" in workbook.sheetnames:
            workbook.remove(workbook["Sheet"])
        
        completed_areas = self.progress["completed_areas"]
        current_area_index = self.progress["current_area_index"]
        
        print(f"Starting from area index {current_area_index}")
        print(f"Already completed areas: {', '.join(completed_areas) if completed_areas else 'None'}")
        
        resuming_area = self.progress["current_progress"]["area_name"]
        if resuming_area:
            for idx, (area_name, _) in enumerate(ahmadi_areas):
                if area_name == resuming_area:
                    print(f"Resuming from area {resuming_area} (index {idx})")
                    current_area_index = idx
                    self.progress["current_area_index"] = idx
                    self.save_progress()
                    break
        
        for idx, (area_name, area_url) in enumerate(ahmadi_areas):
            if area_name in completed_areas and area_name != resuming_area:
                print(f"Skipping already processed area: {area_name}")
                continue
            if idx < current_area_index:
                print(f"Skipping area {area_name} (index {idx} < current index {current_area_index})")
                continue
            
            self.progress["current_area_index"] = idx
            self.save_progress()
            
            try:
                area_results = await self.scrape_and_save_area(area_name, area_url)
                self.create_excel_sheet(workbook, area_name, area_results)
                workbook.save(excel_filename)
                print(f"Updated Excel file: {excel_filename}")
                
                if area_name not in completed_areas:
                    completed_areas.append(area_name)
                    self.progress["completed_areas"] = completed_areas
                self.save_progress()
                await asyncio.sleep(5)
            
            except Exception as e:
                print(f"Error processing area {area_name}: {str(e)}")
                import traceback
                traceback.print_exc()
                self.save_progress()
        
        workbook.save(excel_filename)
        combined_json_filename = os.path.join(self.output_dir, "الاحمدي_all.json")
        with open(combined_json_filename, 'w', encoding='utf-8') as f:
            json.dump(self.scraped_data, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*50}")
        print(f"SCRAPING COMPLETED")
        print(f"Excel file saved: {excel_filename}")
        print(f"Combined JSON saved: {combined_json_filename}")
        
        if len(completed_areas) == len(ahmadi_areas):
            if self.upload_to_drive(excel_filename):
                print(f"Successfully uploaded Excel file to Google Drive")
            else:
                print(f"Failed to upload Excel file to Google Drive")
        else:
            print(f"Scraping incomplete ({len(completed_areas)}/{len(ahmadi_areas)} areas). Skipping upload.")

def create_credentials_file():
    """Create the credentials.json file from environment variable"""
    try:
        credentials_json = os.environ.get('TALABAT_GCLOUD_KEY_JSON')
        if not credentials_json:
            print("ERROR: TALABAT_GCLOUD_KEY_JSON environment variable not found!")
            return False
        with open('credentials.json', 'w') as f:
            f.write(credentials_json)
        print("Successfully created credentials.json")
        return True
    except Exception as e:
        print(f"ERROR: Failed to create credentials.json: {str(e)}")
        return False

async def main():
    """Entry point for the application"""
    if not create_credentials_file():
        print("Could not create credentials.json")
        sys.exit(1)
    
    if not os.path.exists('credentials.json'):
        print("ERROR: credentials.json not found!")
        sys.exit(1)
    
    try:
        scraper = MainScraper()
        await scraper.run()
    except KeyboardInterrupt:
        print("\nProcess interrupted. Saving progress...")
        if 'scraper' in locals():
            scraper.save_progress()
            scraper.save_scraped_data()
        print("Progress and data saved. Exiting.")
    except Exception as e:
        print(f"Critical error: {e}")
        import traceback
        traceback.print_exc()
        if 'scraper' in locals():
            scraper.save_progress()
            scraper.save_scraped_data()
        sys.exit(1)

if __name__ == "__main__":
    scraper = MainScraper()
    scraper.print_progress_details()
    asyncio.run(scraper.run())
