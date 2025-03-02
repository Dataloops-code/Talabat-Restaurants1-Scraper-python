import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


class SavingOnDrive:
    """Class to handle uploading files to Google Drive"""
    
    def __init__(self, credentials_path='credentials.json'):
        """
        Initialize the DriveUploader with Google Drive API credentials.
        
        Args:
            credentials_path: Path to the service account credentials JSON file
        """
        self.credentials_path = credentials_path
        self.drive_service = None
        
        # The folder IDs for the two target locations
        self.target_folders = [
            "15ED49IXFpuL0zzGTHfG7IsPYQLnWJAhg",  # First folder
            "18PiXcppJh7e2RJ2kcw6Mb8-kYiCHPAe2"   # Second folder
        ]
    
    def authenticate(self):
        """
        Authenticate with Google Drive API using service account credentials
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        try:
            # Define the scopes required for Google Drive access
            SCOPES = ['https://www.googleapis.com/auth/drive']
            
            # Load credentials from the service account file
            credentials = Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES)
            
            # Build the Drive API service
            self.drive_service = build('drive', 'v3', credentials=credentials)
            return True
            
        except Exception as e:
            print(f"Authentication error: {str(e)}")
            return False
    
    def upload_file(self, file_path, folder_id, file_name=None):
        """
        Upload a file to a specific Google Drive folder
        
        Args:
            file_path: Path to the file to upload
            folder_id: ID of the folder to upload to
            file_name: Optional name to use for the file in Drive (default: original filename)
            
        Returns:
            str: File ID if upload successful, None otherwise
        """
        try:
            if not self.drive_service:
                if not self.authenticate():
                    return None
            
            # Get the base file name if not provided
            if file_name is None:
                file_name = os.path.basename(file_path)
            
            # Add timestamp to ensure uniqueness and prevent overwriting
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            name_parts = os.path.splitext(file_name)
            unique_file_name = f"{name_parts[0]}_{timestamp}{name_parts[1]}"
            
            # Define file metadata
            file_metadata = {
                'name': unique_file_name,
                'parents': [folder_id]
            }
            
            # Create media object for the file
            media = MediaFileUpload(
                file_path,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                resumable=True
            )
            
            # Execute the upload
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            print(f"File uploaded successfully to folder {folder_id}")
            return file.get('id')
            
        except Exception as e:
            print(f"Upload error: {str(e)}")
            return None
    
    def upload_to_multiple_folders(self, file_path, file_name=None):
        """
        Upload a file to multiple Google Drive folders
        
        Args:
            file_path: Path to the file to upload
            file_name: Optional name to use for the file in Drive
            
        Returns:
            list: List of file IDs for each successful upload
        """
        file_ids = []
        
        for folder_id in self.target_folders:
            file_id = self.upload_file(file_path, folder_id, file_name)
            if file_id:
                file_ids.append(file_id)
        
        return file_ids
