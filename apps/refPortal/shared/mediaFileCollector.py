import os
import aiohttp
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import mimetypes
from urllib.parse import urlparse, unquote
from logging import Logger
import hashlib
import json
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers

class MediaFileCollector:
    """
    Service to collect and store incoming webhook media files (images, PDFs, etc.)
    """
    
    def __init__(self, logger: Logger, base_storage_path: str = None):
        self.logger = logger
        self.base_storage_path = base_storage_path or os.getenv("MEDIA_STORAGE_PATH", "/run/data/media_files")
        self.max_file_size = int(os.getenv("MAX_MEDIA_FILE_SIZE", "50")) * 1024 * 1024  # 50MB default
        self.allowed_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.webp',  # Images
            '.pdf',  # Documents
            '.mp4', '.avi', '.mov', '.wmv',  # Videos
            '.mp3', '.wav', '.ogg', '.m4a',  # Audio
            '.doc', '.docx', '.txt', '.rtf',  # Text documents
            '.xls', '.xlsx', '.csv'  # Spreadsheets
        }
        
        # Create storage directories
        self._create_storage_directories()
    
    def _create_storage_directories(self):
        """Create necessary storage directories"""
        directories = [
            self.base_storage_path,
            os.path.join(self.base_storage_path, "images"),
            os.path.join(self.base_storage_path, "documents"),
            os.path.join(self.base_storage_path, "videos"),
            os.path.join(self.base_storage_path, "audio"),
            os.path.join(self.base_storage_path, "other")
        ]
        
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Created/verified directory: {directory}")
    
    def _get_file_extension(self, url: str, content_type: str = None) -> str:
        """Determine file extension from URL and content type"""
        # First try to get extension from URL
        parsed_url = urlparse(url)
        path = unquote(parsed_url.path)
        _, ext = os.path.splitext(path.lower())
        
        if ext and ext in self.allowed_extensions:
            return ext
        
        # If no valid extension from URL, try content type
        if content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext and ext in self.allowed_extensions:
                return ext
        
        # Default to .bin for unknown types
        return '.bin'
    
    def _get_storage_category(self, extension: str) -> str:
        """Determine storage category based on file extension"""
        if extension in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            return "images"
        elif extension in {'.pdf', '.doc', '.docx', '.txt', '.rtf', '.xls', '.xlsx', '.csv'}:
            return "documents"
        elif extension in {'.mp4', '.avi', '.mov', '.wmv'}:
            return "videos"
        elif extension in {'.mp3', '.wav', '.ogg', '.m4a'}:
            return "audio"
        else:
            return "other"
    
    def _generate_filename(self, url: str, content_type: str, from_mobile: str, fileType: str, message_sid: str) -> str:
        """Generate a unique filename for the media file"""
        # Create a hash of the URL for uniqueness
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        
        # Get file extension
        extension = self._get_file_extension(url, content_type)
        
        # Create timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Generate filename: timestamp_mobile_hash.extension
        filename = f"{timestamp}_{from_mobile}_{fileType}_{url_hash}{extension}"
        
        return filename

    async def download_media_file(self, media_url: str, content_type: str, from_mobile: str, 
                                 message_sid: str, timeout: int = 30, custom_headers: Dict = None) -> Optional[Dict]:
        """
        Download a single media file from URL
        
        Args:
            media_url: URL of the media file
            content_type: MIME type of the media file
            from_mobile: Mobile number of sender
            message_sid: Message SID for tracking
            timeout: Download timeout in seconds
            
        Returns:
            Dict with file info or None if download failed
        """
        try:
            self.logger.info(f"Starting download of media file from {media_url}")
            
            # Generate filename and storage path
            filename = self._generate_filename(media_url, content_type, from_mobile, fileType, message_sid)
            extension = self._get_file_extension(media_url, content_type)
            category = self._get_storage_category(extension)
            storage_path = os.path.join(self.base_storage_path, category, filename)
            
            # Download file
            headers = custom_headers or {}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(media_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.error(f"Failed to download media file: HTTP {response.status}")
                        return None
                    
                    # Check file size
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.max_file_size:
                        self.logger.error(f"Media file too large: {content_length} bytes (max: {self.max_file_size})")
                        return None
                    
                    # Download content
                    content = await response.read()
                    
                    # Check actual file size
                    if len(content) > self.max_file_size:
                        self.logger.error(f"Media file too large: {len(content)} bytes (max: {self.max_file_size})")
                        return None
                    
                    # Save file
                    with open(storage_path, 'wb') as f:
                        f.write(content)
                    
                    # Get file info
                    file_size = len(content)
                    actual_content_type = response.headers.get('content-type', content_type)
                    
                    file_info = {
                        'original_url': media_url,
                        'filename': filename,
                        'storage_path': storage_path,
                        'relative_path': os.path.relpath(storage_path, self.base_storage_path),
                        'content_type': actual_content_type,
                        'file_size': file_size,
                        'extension': extension,
                        'category': category,
                        'from_mobile': from_mobile,
                        'message_sid': message_sid,
                        'download_timestamp': datetime.now().isoformat(),
                        'url_hash': hashlib.md5(media_url.encode()).hexdigest()
                    }
                    
                    self.logger.info(f"Successfully downloaded media file: {filename} ({file_size} bytes)")
                    return file_info
                    
        except asyncio.TimeoutError:
            self.logger.error(f"Timeout downloading media file from {media_url}")
            return None
        except Exception as e:
            self.logger.error(f"Error downloading media file from {media_url}: {str(e)}")
            return None

    async def save_media_file(self, tag: str, fileType: str, mediaInfo:dict, fromMobileNo: str, currentMessageId: str, timeout: int = 30) -> Optional[Dict]:
        try:
            # Generate filename and storage path
            extension = self._get_file_extension(url=mediaInfo.get('url'), content_type=mediaInfo.get('mime_type'))
            category = self._get_storage_category(extension=extension)
            filename = self._generate_filename(url=mediaInfo.get('url'), content_type=mediaInfo.get('mime_type'), from_mobile=fromMobileNo, fileType=fileType, message_sid=currentMessageId)
            storage_path = os.path.join(self.base_storage_path, category, tag, filename)

            helpers.validatePath(file=storage_path)
            with open(storage_path, 'wb') as f:
                f.write(mediaInfo['content'])
            
            # Get file info
            file_info = {
                'original_url': mediaInfo.get('url'),
                'filename': filename,
                'storage_path': storage_path,
                'relative_path': os.path.relpath(storage_path, self.base_storage_path),
                'content_type': mediaInfo['actual_content_type'],
                'file_size': mediaInfo['actual_file_size'],
                'extension': extension,
                'category': category,
                'from_mobile': fromMobileNo,
                'message_sid': currentMessageId,
                'download_timestamp': datetime.now().isoformat(),
                'url_hash': hashlib.md5(mediaInfo.get('url').encode()).hexdigest()
            }
                
            self.logger.info(f"Successfully downloaded media file: {filename} ({mediaInfo['actual_file_size']} bytes)")
            return file_info
                    
        except Exception as ex:
            self.logger.error(f"Error save media file from {mediaInfo.get('id')}: {str(ex)}")
            return None
        
    def get_media_file_info(self, file_id: str) -> Optional[Dict]:
        """
        Get media file information by file ID
        
        Args:
            file_id: File ID (URL hash)
            
        Returns:
            File info dict or None if not found
        """
        try:
            metadata_file = os.path.join(
                self.base_storage_path, 
                'metadata', 
                f"{file_id}.json"
            )
            
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    return json.load(f)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting media file info: {str(e)}")
            return None
    
    def cleanup_old_files(self, days_old: int = 30) -> int:
        """
        Clean up old media files and their metadata
        
        Args:
            days_old: Number of days after which files are considered old
            
        Returns:
            Number of files cleaned up
        """
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=days_old)
            cleaned_count = 0
            
            # Clean up files in all categories
            for category in ['images', 'documents', 'videos', 'audio', 'other']:
                category_path = os.path.join(self.base_storage_path, category)
                if not os.path.exists(category_path):
                    continue
                
                for filename in os.listdir(category_path):
                    file_path = os.path.join(category_path, filename)
                    if os.path.isfile(file_path):
                        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if file_time < cutoff_date:
                            os.remove(file_path)
                            cleaned_count += 1
                            self.logger.debug(f"Cleaned up old file: {file_path}")
            
            # Clean up metadata files
            metadata_path = os.path.join(self.base_storage_path, 'metadata')
            if os.path.exists(metadata_path):
                for filename in os.listdir(metadata_path):
                    if filename.endswith('.json'):
                        metadata_file = os.path.join(metadata_path, filename)
                        file_time = datetime.fromtimestamp(os.path.getmtime(metadata_file))
                        if file_time < cutoff_date:
                            os.remove(metadata_file)
                            self.logger.debug(f"Cleaned up old metadata: {metadata_file}")
            
            self.logger.info(f"Cleaned up {cleaned_count} old media files")
            return cleaned_count
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old files: {str(e)}")
            return 0
