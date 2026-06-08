import re
import urllib.parse
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse, parse_qs

class URLParser:
    """Utility class for finding URLs in text and parsing their parameters"""
    
    def __init__(self):
        # Regex pattern to match URLs (http, https, ftp, mailto, etc.)
        self.url_pattern = re.compile(
            r'(?:https?://|ftp://|mailto:|tel:)(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
    
    def find_urls(self, text: str) -> List[str]:
        """
        Find all URLs in the given text
        
        Args:
            text (str): The text to search for URLs
            
        Returns:
            List[str]: List of found URLs
        """
        return self.url_pattern.findall(text)
    
    def parse_url_params(self, url: str) -> Dict[str, List[str]]:
        """
        Parse URL parameters from a given URL
        
        Args:
            url (str): The URL to parse
            
        Returns:
            Dict[str, List[str]]: Dictionary of parameter names and their values
        """
        try:
            parsed_url = urlparse(url)
            return parse_qs(parsed_url.query)
        except Exception as e:
            print(f"Error parsing URL {url}:", e)
            return {}
    
    def extract_url_info(self, url: str) -> Dict[str, any]:
        """
        Extract comprehensive information from a URL
        
        Args:
            url (str): The URL to analyze
            
        Returns:
            Dict[str, any]: Dictionary containing URL components and parameters
        """
        try:
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)
            
            return {
                'full_url': url,
                'scheme': parsed_url.scheme,
                'netloc': parsed_url.netloc,
                'path': parsed_url.path,
                'params': parsed_url.params,
                'query': parsed_url.query,
                'fragment': parsed_url.fragment,
                'query_params': params,
                'domain': parsed_url.netloc.split(':')[0] if ':' in parsed_url.netloc else parsed_url.netloc,
                'port': parsed_url.port if parsed_url.port else (443 if parsed_url.scheme == 'https' else 80)
            }
        except Exception as e:
            print(f"Error extracting URL info from {url}:", e)
            return {'full_url': url, 'error': str(e)}
    
    def find_and_parse_urls(self, text: str) -> List[Dict[str, any]]:
        """
        Find all URLs in text and parse their information
        
        Args:
            text (str): The text to search for URLs
            
        Returns:
            List[Dict[str, any]]: List of dictionaries containing URL information
        """
        urls = self.find_urls(text)
        return [self.extract_url_info(url) for url in urls]
    
    def get_domain_from_url(self, url: str) -> Optional[str]:
        """
        Extract domain from URL
        
        Args:
            url (str): The URL to extract domain from
            
        Returns:
            Optional[str]: The domain name or None if parsing fails
        """
        try:
            parsed_url = urlparse(url)
            return parsed_url.netloc.split(':')[0] if ':' in parsed_url.netloc else parsed_url.netloc
        except:
            return None
    
    def is_valid_url(self, url: str) -> bool:
        """
        Check if a string is a valid URL
        
        Args:
            url (str): The string to validate
            
        Returns:
            bool: True if valid URL, False otherwise
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False


def find_urls_in_text(text: str) -> List[str]:
    """
    Convenience function to find URLs in text
    
    Args:
        text (str): The text to search for URLs
        
    Returns:
        List[str]: List of found URLs
    """
    parser = URLParser()
    return parser.find_urls(text)


def parse_url_parameters(url: str) -> Dict[str, List[str]]:
    """
    Convenience function to parse URL parameters
    
    Args:
        url (str): The URL to parse
        
    Returns:
        Dict[str, List[str]]: Dictionary of parameter names and their values
    """
    parser = URLParser()
    return parser.parse_url_params(url)


if __name__ == "__main__":
    # Test with the provided text
    test_text = """שיבוץ חדש (מאושר)
*התאחדות לכדורגל בישראל*
תאריך: 25/10/25 13:30
יום: שבת
מסגרת משחקים: גביע ילדים ב' ע"ש שמואל סוחר ז"ל
משחק: מכבי יפו קביליו רחו מג'אר ז"ל - הפועל ב"ש לבן
תפקיד: שופט ראשי
סבב: 8
מחזור: 2
מגרש: תל אביב יפו נוה גולן
סטטוס: מאושר

תפקיד: שופט ראשי
* שם: שחר גיא
* סטטוס: מאשר
* דרג: דרג אזורי-טרומים
* טלפון: +972547799979
* כתובת: אהרון גולדשטיין 2 גבעתיים
עדכן לוח שנה https://api.refereex.com/api/file/40187e0c"""
    
    parser = URLParser()
    
    print("=== URL Parser Test ===")
    print(f"Input text length: {len(test_text)} characters")
    print()
    
    # Find URLs
    urls = parser.find_urls(test_text)
    print(f"Found {len(urls)} URLs:")
    for i, url in enumerate(urls, 1):
        print(f"  {i}. {url}")
    print()
    
    # Parse each URL
    for i, url in enumerate(urls, 1):
        print(f"=== URL {i} Analysis ===")
        url_info = parser.extract_url_info(url)
        
        print(f"Full URL: {url_info['full_url']}")
        print(f"Scheme: {url_info['scheme']}")
        print(f"Domain: {url_info['domain']}")
        print(f"Path: {url_info['path']}")
        print(f"Query: {url_info['query']}")
        print(f"Fragment: {url_info['fragment']}")
        print(f"Query Parameters: {url_info['query_params']}")
        print(f"Port: {url_info['port']}")
        print()
