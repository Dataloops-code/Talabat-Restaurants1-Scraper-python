import asyncio
import json
import os
import sys
import subprocess
from typing import Dict, List, Tuple
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter
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
        """Load progress from JSON file if it exists"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                print(f"Loaded progress from {self.progress_file}")
                return progress
            except Exception as e:
                print(f"Error loading progress file: {str(e)}")
        
        # Return default empty progress
        return {
            "completed_areas": [],
            "current_area_index": 0,
            "last_updated": None,
            "all_results": {}
        }
    
    def save_progress(self):
        """Save current progress to JSON file"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=2, ensure_ascii=False)
            print(f"Saved progress to {self.progress_file}")
        except Exception as e:
            print(f"Error saving progress file: {str(e)}")
    
    async def scrape_and_save_area(self, area_name: str, area_url: str) -> List[Dict]:
        """
        Scrape restaurants for a specific area and save to JSON
        
        Args:
            area_name: Name of the area (in Arabic)
            area_url: Talabat URL for the area
            
        Returns:
            List of restaurant data dictionaries
        """
        print(f"\n{'='*50}")
        print(f"SCRAPING AREA: {area_name}")
        print(f"URL: {area_url}")
        print(f"{'='*50}\n")
        
        # Scrape the data
        results = await self.talabat_scraper.scrape_all_restaurants_by_page(area_url)
        
        # Save area results to individual JSON file
        json_filename = os.path.join(self.output_dir, f"{area_name}.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            
        print(f"Saved {len(results)} restaurants for {area_name} to {json_filename}")
        
        return results
    
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
        """Main execution function to scrape all areas with resume capability."""
        # Define governorate and its areas with their URLs
        ahmadi_areas = [
            # Area Name, URL
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
        
        # Create an Excel workbook for the governorate or load existing
        excel_filename = os.path.join(self.output_dir, "الاحمدي.xlsx")
        
        if os.path.exists(excel_filename) and "all_results" in self.progress and self.progress["all_results"]:
            # Load existing workbook
            print(f"Loading existing Excel file: {excel_filename}")
            workbook = pd.ExcelFile(excel_filename)
            existing_sheets = workbook.sheet_names
            
            # Create a new workbook and copy existing sheets
            new_workbook = Workbook()
            if "Sheet" in new_workbook.sheetnames:
                new_workbook.remove(new_workbook["Sheet"])
            
            # We'll recreate the workbook since openpyxl can't directly load for append
            workbook = new_workbook
        else:
            # Create a new workbook
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
        
        # Process each area in the governorate
        for idx, (area_name, area_url) in enumerate(ahmadi_areas):
            # Skip already completed areas
            if area_name in completed_areas:
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
                completed_areas.append(area_name)
                self.progress["completed_areas"] = completed_areas
                
                # Update timestamp
                import datetime
                self.progress["last_updated"] = datetime.datetime.now().isoformat()
                
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
        
    scraper = MainScraper()
    await scraper.run()

if __name__ == "__main__":
    asyncio.run(main())


# import asyncio
# import json
# import os
# import sys
# from typing import Dict, List, Tuple
# import pandas as pd
# from openpyxl import Workbook
# from openpyxl.utils.dataframe import dataframe_to_rows
# from openpyxl.utils import get_column_letter
# from talabat_main_scraper import TalabatScraper
# from SavingOnDrive import SavingOnDrive


# class MainScraper:
#     def __init__(self):
#         self.talabat_scraper = TalabatScraper()
#         self.output_dir = "output"
#         self.drive_uploader = SavingOnDrive('credentials.json')
        
#         # Create output directory if it doesn't exist
#         os.makedirs(self.output_dir, exist_ok=True)
    
#     async def scrape_and_save_area(self, area_name: str, area_url: str) -> List[Dict]:
#         """
#         Scrape restaurants for a specific area and save to JSON
        
#         Args:
#             area_name: Name of the area (in Arabic)
#             area_url: Talabat URL for the area
            
#         Returns:
#             List of restaurant data dictionaries
#         """
#         print(f"\n{'='*50}")
#         print(f"SCRAPING AREA: {area_name}")
#         print(f"URL: {area_url}")
#         print(f"{'='*50}\n")
        
#         # Scrape the data
#         results = await self.talabat_scraper.scrape_all_restaurants_by_page(area_url)
        
#         # Save area results to individual JSON file
#         json_filename = os.path.join(self.output_dir, f"{area_name}.json")
#         with open(json_filename, 'w', encoding='utf-8') as f:
#             json.dump(results, f, indent=2, ensure_ascii=False)
            
#         print(f"Saved {len(results)} restaurants for {area_name} to {json_filename}")
        
#         return results
    
#     def create_excel_sheet(self, workbook, sheet_name: str, data: List[Dict]):
#         """
#         Create a sheet in the Excel workbook for the specified area data
        
#         Args:
#             workbook: Excel workbook to add sheet to
#             sheet_name: Name of the sheet (area name in Arabic)
#             data: List of restaurant data dictionaries
#         """
#         # Create sheet
#         sheet = workbook.create_sheet(title=sheet_name)
        
#         # Extract key information for the Excel file
#         simplified_data = []
#         for restaurant in data:
#             # Basic information
#             restaurant_info = {
#                 "Name": restaurant.get("name", ""),
#                 "Cuisine": restaurant.get("cuisine", ""),
#                 "Rating": restaurant.get("rating", ""),
#                 "Delivery Time": restaurant.get("delivery_time", ""),
#                 "Delivery Fee": restaurant.get("delivery_fee", ""),
#                 "Min Order": restaurant.get("min_order", ""),
#                 "URL": restaurant.get("url", ""),
#             }
            
#             # Add info from restaurant details if available
#             if restaurant.get("info"):
#                 restaurant_info.update({
#                     "Address": restaurant["info"].get("Address", ""),
#                     "Working Hours": restaurant["info"].get("Working Hours", ""),
#                 })
            
#             # Add rating from reviews if available
#             if restaurant.get("reviews") and restaurant["reviews"].get("Rating_value"):
#                 restaurant_info["Rating Value"] = restaurant["reviews"]["Rating_value"]
#                 restaurant_info["Ratings Count"] = restaurant["reviews"].get("Ratings_count", "")
#                 restaurant_info["Reviews Count"] = restaurant["reviews"].get("Reviews_count", "")
            
#             # Count menu categories and items
#             if restaurant.get("menu_items"):
#                 restaurant_info["Menu Categories"] = len(restaurant["menu_items"])
#                 item_count = sum(len(items) for items in restaurant["menu_items"].values())
#                 restaurant_info["Menu Items"] = item_count
            
#             simplified_data.append(restaurant_info)
        
#         # Create DataFrame
#         if simplified_data:
#             df = pd.DataFrame(simplified_data)
            
#             # Write data to sheet
#             for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
#                 for c_idx, value in enumerate(row, 1):
#                     sheet.cell(row=r_idx, column=c_idx, value=value)
            
#             # Auto-adjust column widths
#             for column in sheet.columns:
#                 max_length = 0
#                 column_letter = get_column_letter(column[0].column)
#                 for cell in column:
#                     try:
#                         if len(str(cell.value)) > max_length:
#                             max_length = len(str(cell.value))
#                     except:
#                         pass
#                 adjusted_width = (max_length + 2)
#                 sheet.column_dimensions[column_letter].width = min(adjusted_width, 50)
#         else:
#             sheet.cell(row=1, column=1, value="No data found for this area")
    
#     def upload_to_drive(self, file_path):
#         """
#         Upload Excel file to Google Drive folders
        
#         Args:
#             file_path: Path to the Excel file to upload
            
#         Returns:
#             bool: True if upload successful, False otherwise
#         """
#         print(f"\nUploading {file_path} to Google Drive...")
        
#         try:
#             # Authenticate with Google Drive
#             if not self.drive_uploader.authenticate():
#                 print("Failed to authenticate with Google Drive")
#                 return False
            
#             # Upload the file to both folders
#             file_ids = self.drive_uploader.upload_to_multiple_folders(file_path)
            
#             if len(file_ids) == 2:
#                 print(f"Successfully uploaded file to both Google Drive folders")
#                 print(f"File IDs: {file_ids}")
#                 return True
#             else:
#                 print(f"Partially uploaded file to {len(file_ids)} out of 2 folders")
#                 return False
                
#         except Exception as e:
#             print(f"Error uploading to Google Drive: {str(e)}")
#             return False
    
#     async def run(self):
#         """Main execution function to scrape all areas."""
#         # Define governorate and its areas with their URLs
#         ahmadi_areas = [
#             # Area Name, URL
#             ("الظهر", "https://www.talabat.com/kuwait/restaurants/59/dhaher"),
#             ("الرقه", "https://www.talabat.com/kuwait/restaurants/37/riqqa"),
#             ("هدية", "https://www.talabat.com/kuwait/restaurants/30/hadiya"),
#             ("المنقف", "https://www.talabat.com/kuwait/restaurants/32/mangaf"),
#             ("أبو حليفة", "https://www.talabat.com/kuwait/restaurants/2/abu-halifa"),
#             ("الفنطاس", "https://www.talabat.com/kuwait/restaurants/38/fintas"),
#             ("العقيلة", "https://www.talabat.com/kuwait/restaurants/79/egaila"),
#             ("الصباحية", "https://www.talabat.com/kuwait/restaurants/31/sabahiya"),
#             ("الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
#             ("الفحيحيل", "https://www.talabat.com/kuwait/restaurants/5/fahaheel"),
#             ("شرق الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi"),
#             ("ضاحية علي صباح السالم", "https://www.talabat.com/kuwait/restaurants/82/ali-sabah-al-salem-umm-al-hayman"),
#             ("ميناء عبد الله", "https://www.talabat.com/kuwait/restaurants/100/mina-abdullah"),
#             ("بنيدر", "https://www.talabat.com/kuwait/restaurants/6650/bnaider"),
#             ("الزور", "https://www.talabat.com/kuwait/restaurants/2053/zour"),
#             ("الجليعة", "https://www.talabat.com/kuwait/restaurants/6860/al-julaiaa"),
#             ("المهبولة", "https://www.talabat.com/kuwait/restaurants/24/mahboula"),
#             ("النويصيب", "https://www.talabat.com/kuwait/restaurants/2054/nuwaiseeb"),
#             ("الخيران", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
#             ("الوفرة", "https://www.talabat.com/kuwait/restaurants/2057/wafra-farms"),
#             ("ضاحية فهد الأحمد", "https://www.talabat.com/kuwait/restaurants/98/fahad-al-ahmed"),
#             ("ضاحية جابر العلي", "https://www.talabat.com/kuwait/restaurants/60/jaber-al-ali"),
#             ("مدينة صباح الأحمد السكنية", "https://www.talabat.com/kuwait/restaurants/6931/sabah-al-ahmad-2"),
#             ("مدينة صباح الأحمد البحرية", "https://www.talabat.com/kuwait/restaurants/2726/khairan"),
#             ("ميناء الأحمدي", "https://www.talabat.com/kuwait/restaurants/3/al-ahmadi")
#         ]
        
#         # Create an Excel workbook for the governorate
#         workbook = Workbook()
#         # Remove default sheet
#         if "Sheet" in workbook.sheetnames:
#             workbook.remove(workbook["Sheet"])
        
#         # Track all results for the combined JSON
#         all_results = {}
        
#         # Process each area in the governorate
#         for area_name, area_url in ahmadi_areas:
#             try:
#                 # Scrape area data and save to JSON
#                 area_results = await self.scrape_and_save_area(area_name, area_url)
                
#                 # Add to all results
#                 all_results[area_name] = area_results
                
#                 # Create Excel sheet for this area
#                 self.create_excel_sheet(workbook, area_name, area_results)
                
#                 # Save progress after each area
#                 excel_filename = os.path.join(self.output_dir, "الاحمدي.xlsx")
#                 workbook.save(excel_filename)
#                 print(f"Updated Excel file: {excel_filename}")
                
#                 # Brief pause between areas
#                 await asyncio.sleep(5)
                
#             except Exception as e:
#                 print(f"Error processing area {area_name}: {str(e)}")
#                 import traceback
#                 traceback.print_exc()
        
#         # Save the final Excel file
#         excel_filename = os.path.join(self.output_dir, "الاحمدي.xlsx")
#         workbook.save(excel_filename)
        
#         # Save combined results to a single JSON file
#         combined_json_filename = os.path.join(self.output_dir, "الاحمدي_all.json")
#         with open(combined_json_filename, 'w', encoding='utf-8') as f:
#             json.dump(all_results, f, indent=2, ensure_ascii=False)
            
#         print(f"\n{'='*50}")
#         print(f"SCRAPING COMPLETED")
#         print(f"Excel file saved: {excel_filename}")
#         print(f"Combined JSON saved: {combined_json_filename}")
        
#         # Upload Excel to Google Drive
#         excel_file_path = os.path.join(os.getcwd(), excel_filename)
#         upload_success = self.upload_to_drive(excel_file_path)
        
#         if upload_success:
#             print(f"Successfully uploaded Excel file to Google Drive")
#         else:
#             print(f"Failed to upload Excel file to Google Drive")
            
#         print(f"{'='*50}\n")


# def create_credentials_file():
#     """Create the credentials.json file from environment variable."""
#     try:
#         # Get credentials from environment variable
#         credentials_json = os.environ.get('TALABAT_GCLOUD_KEY_JSON')
        
#         if not credentials_json:
#             print("ERROR: TALABAT_GCLOUD_KEY_JSON environment variable not found!")
#             print("Please set the TALABAT_GCLOUD_KEY_JSON environment variable with the Google service account credentials")
#             return False
        
#         # Write credentials to file
#         with open('credentials.json', 'w') as f:
#             f.write(credentials_json)
        
#         print("Successfully created credentials.json from environment variable")
#         return True
    
#     except Exception as e:
#         print(f"ERROR: Failed to create credentials.json: {str(e)}")
#         return False


# async def main():
#     """Entry point for the application."""
#     # Create credentials file from environment variable
#     if not create_credentials_file():
#         print("Could not create credentials.json from environment variable")
#         sys.exit(1)
        
#     # Check if credentials file exists
#     if not os.path.exists('credentials.json'):
#         print("ERROR: credentials.json not found!")
#         print("Please create a service account in Google Cloud Console and download the credentials")
#         print("Save the file as 'credentials.json' in the same directory as this script")
#         sys.exit(1)
        
#     scraper = MainScraper()
#     await scraper.run()

# if __name__ == "__main__":
#     asyncio.run(main())
