#!/usr/bin/env python3
"""
CV Tailoring Script using Google Gemini

This script:
1. Fetches a job description from a URL
2. Reads your CV PDF file
3. Uses Gemini AI to tailor the CV specifically for the job description
4. Outputs the tailored CV without annotations
"""

import os
import sys
import argparse
import requests
from pathlib import Path
import google.generativeai as genai
from PyPDF2 import PdfReader
import io
import re
import time

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


def fetch_job_description(url: str) -> str:
    """
    Fetch job description from URL
    
    Args:
        url: URL of the job description
        
    Returns:
        Text content of the job description
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Extract text from HTML if it's an HTML page
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' in content_type and HAS_BEAUTIFULSOUP:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer"]):
                script.decompose()
            # Get text
            text = soup.get_text(separator='\n', strip=True)
            return text
        elif 'html' in content_type:
            # Fallback: basic text extraction without BeautifulSoup
            # Remove HTML tags roughly
            import re
            text = re.sub(r'<[^>]+>', '', response.text)
            text = re.sub(r'\s+', ' ', text)
            return text
        else:
            # Plain text or other format
            return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching job description from URL: {e}")
        sys.exit(1)


def extract_text_from_pdf(pdf_path: str) -> tuple[str, dict, dict]:
    """
    Extract text, hyperlinks, and formatting from PDF file
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Tuple of (extracted text with formatting markers, dictionary of hyperlinks, formatting info)
    """
    try:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"CV PDF file not found: {pdf_path}")
        
        hyperlinks = {}  # Dictionary to store hyperlinks: {link_text: url}
        formatting_info = {}  # Store formatting information
        
        if HAS_PYMUPDF:
            # Use PyMuPDF for better formatting and hyperlink extraction
            doc = fitz.open(str(pdf_path))
            text_parts = []
            link_rects = {}  # Store link rectangles to match with text
            
            # Track page margins to normalize indentation
            page_margins = {}  # {page_num: left_margin}
            
            for page_num, page in enumerate(doc):
                # First, collect all hyperlinks with their rectangles
                links = page.get_links()
                for link in links:
                    if "uri" in link:
                        url = link["uri"]
                        rect = link.get("from", None)
                        if rect:
                            link_rects[tuple(rect)] = url
                
                # Extract text with formatting
                text_dict = page.get_text("dict")
                
                # Find the leftmost text position on this page (to normalize indentation)
                min_x = float('inf')
                for block in text_dict["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                bbox = span.get("bbox", None)
                                if bbox and bbox[0] < min_x:
                                    min_x = bbox[0]
                
                if min_x == float('inf'):
                    min_x = 72  # Default margin (1 inch)
                page_margins[page_num] = min_x
                
                for block in text_dict["blocks"]:
                    if "lines" in block:  # Text block
                        for line in block["lines"]:
                            line_text_parts = []
                            line_x0 = None  # Left position of this line
                            
                            for span in line["spans"]:
                                text = span["text"]
                                bbox = span.get("bbox", None)  # Bounding box of this span: [x0, y0, x1, y1]
                                font = span.get("font", "")
                                size = span.get("size", 11)
                                flags = span.get("flags", 0)
                                color = span.get("color", 0)
                                
                                # Track the leftmost position of this line
                                if bbox and (line_x0 is None or bbox[0] < line_x0):
                                    line_x0 = bbox[0]
                                
                                # Determine style
                                is_bold = flags & 16  # Bit 4 = bold
                                is_italic = flags & 1  # Bit 0 = italic
                                
                                # Convert color from integer to hex
                                color_hex = f"#{color:06x}" if color > 0 else "#000000"
                                
                                # Check if this text span overlaps with a hyperlink
                                link_url = None
                                if bbox:
                                    for link_rect, url in link_rects.items():
                                        # Check if bbox overlaps with link_rect
                                        if (bbox[0] <= link_rect[2] and bbox[2] >= link_rect[0] and
                                            bbox[1] <= link_rect[3] and bbox[3] >= link_rect[1]):
                                            link_url = url
                                            hyperlinks[text.strip()] = url
                                            break
                                
                                # Build formatting tags (nested properly)
                                formatted_text = text
                                if is_bold:
                                    formatted_text = f"<b>{formatted_text}</b>"
                                if is_italic:
                                    formatted_text = f"<i>{formatted_text}</i>"
                                if color_hex != "#000000":
                                    formatted_text = f'<font color="{color_hex}">{formatted_text}</font>'
                                if size != 11:
                                    formatted_text = f'<font size="{int(size)}">{formatted_text}</font>'
                                
                                # If this is a hyperlink, wrap it
                                if link_url:
                                    # Escape the URL for use in href attribute
                                    escaped_url = link_url.replace('&', '&amp;').replace('"', '&quot;')
                                    formatted_text = f'<link href="{escaped_url}"><u>{formatted_text}</u></link>'
                                
                                line_text_parts.append(formatted_text)
                                
                                # Store formatting info for this text
                                formatting_info[text.strip()] = {
                                    'font': font,
                                    'size': size,
                                    'bold': bool(is_bold),
                                    'italic': bool(is_italic),
                                    'color': color_hex,
                                    'url': link_url
                                }
                            
                            # Calculate indentation for this line (relative to page margin)
                            if line_x0 is not None:
                                indent = line_x0 - page_margins[page_num]
                                # Store indentation info - use the full line text as key
                                line_text = "".join(line_text_parts).strip()
                                if line_text:
                                    # Store indentation in points (1 point = 1/72 inch)
                                    # Round to nearest 5 points for consistency
                                    indent_points = round(indent / 5) * 5
                                    formatting_info[f"__INDENT__{line_text}"] = indent_points
                                    # Add indentation marker to text (we'll process this later)
                                    if indent_points > 10:  # Only mark significant indentation
                                        # Add a special marker that we can detect later
                                        line_text_parts.insert(0, f"__INDENT_{indent_points}__")
                            
                            text_parts.extend(line_text_parts)
                            text_parts.append("\n")
                
                # Also collect any remaining links that weren't matched
                for link in links:
                    if "uri" in link:
                        url = link["uri"]
                        rect = link.get("from", None)
                        if rect:
                            try:
                                link_text = page.get_textbox(rect)
                                if link_text and link_text.strip() and link_text.strip() not in hyperlinks:
                                    hyperlinks[link_text.strip()] = url
                            except:
                                if url not in hyperlinks.values():
                                    hyperlinks[url] = url
            
            doc.close()
            text = "".join(text_parts)
            
        else:
            # Fallback to PyPDF2
            reader = PdfReader(str(pdf_path))
            text = ""
            
            for page in reader.pages:
                page_text = page.extract_text()
                text += page_text + "\n"
                
                # Extract hyperlinks/annotations from the page
                if '/Annots' in page:
                    for annot in page['/Annots']:
                        obj = annot.get_object()
                        if obj.get('/Subtype') == '/Link' and '/A' in obj:
                            uri_obj = obj['/A']
                            if '/URI' in uri_obj:
                                url = uri_obj['/URI']
                                hyperlinks[url] = url
        
        return text, hyperlinks, formatting_info
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        sys.exit(1)


def tailor_cv_with_gemini(job_description: str, cv_text: str, api_key: str, model_name: str = None) -> str:
    """
    Use Gemini to tailor CV based on job description
    
    Args:
        job_description: Job description text
        cv_text: Original CV text
        api_key: Google Gemini API key
        model_name: Optional model name (will try to find available model if not provided)
        
    Returns:
        Tailored CV text
    """
    try:
        # Configure Gemini
        genai.configure(api_key=api_key)
        
        # Try to find an available model if not specified
        if not model_name:
            # List of models to try in order of preference
            model_candidates = [
                'gemini-1.5-pro-latest',
                'gemini-1.5-pro',
                'gemini-1.5-flash-latest',
                'gemini-1.5-flash',
                'gemini-pro',
            ]
            
            # Try to list available models
            try:
                available_models = []
                for m in genai.list_models():
                    model_id = m.name.replace('models/', '')
                    if hasattr(m, 'supported_generation_methods') and 'generateContent' in m.supported_generation_methods:
                        available_models.append(model_id)
                
                if available_models:
                    print(f"Available models: {', '.join(available_models[:5])}")
                    
                    # Find the first candidate that's available
                    for candidate in model_candidates:
                        if candidate in available_models:
                            model_name = candidate
                            break
                    
                    if not model_name:
                        # Fallback to first available model
                        model_name = available_models[0]
                        print(f"Using available model: {model_name}")
                else:
                    # No models found, use default
                    model_name = 'gemini-pro'
                    print(f"Could not list models, trying default: {model_name}")
            except Exception as e:
                print(f"Could not list models ({e}), trying defaults...")
                model_name = 'gemini-pro'
        
        print(f"Using model: {model_name}")
        
        # Initialize the model
        model = genai.GenerativeModel(model_name)
        
        # Create the prompt
        prompt = f"""You are an expert CV writer. I will provide you with:
1. A job description
2. My current CV (with formatting markers)

Please tailor my CV specifically for this job description. Make it highly relevant and compelling for this position.

Requirements:
- Tailor the CV to match the job requirements and keywords
- Highlight relevant experience and skills
- Reorganize sections if needed to emphasize the most relevant qualifications
- Keep all factual information accurate (dates, companies, etc.)
- Make the CV more compelling for this specific role
- PRESERVE ALL FORMATTING from the original CV:
  * Keep all <b>bold</b> text as bold
  * Keep all <i>italic</i> text as italic
  * Keep all <font color="...">colored</font> text with the same colors
  * Keep all <font size="...">sized</font> text with the same sizes
- PRESERVE ALL HYPERLINKS from the original CV (e.g., LinkedIn, email, website URLs)
- Format hyperlinks as [link text](URL) or keep them as plain URLs if they appear in the text
- Maintain the same visual structure and formatting style
- Do NOT add any annotations, comments, or explanations
- Return ONLY the tailored CV content with all formatting markers preserved, nothing else

Job Description:
{job_description}

Current CV:
{cv_text}

Please provide the tailored CV now:"""

        # Generate response with retry logic for rate limiting
        print("Sending request to Gemini...")
        max_retries = 5
        retry_delay = 1  # Start with 1 second
        
        for attempt in range(max_retries):
            try:
                response = model.generate_content(prompt)
                
                if not response or not response.text:
                    raise Exception("Empty response from Gemini API")
                
                return response.text
                
            except Exception as e:
                error_msg = str(e)
                
                # Check if it's a rate limit error (429)
                if "429" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    # Try to extract retry delay from error message
                    retry_seconds = None
                    delay_match = re.search(r'retry.*?(\d+\.?\d*)\s*seconds?', error_msg, re.IGNORECASE)
                    if delay_match:
                        retry_seconds = float(delay_match.group(1))
                    else:
                        # Use exponential backoff
                        retry_seconds = retry_delay * (2 ** attempt)
                    
                    if attempt < max_retries - 1:
                        print(f"\n⚠️  Rate limit exceeded. Waiting {retry_seconds:.1f} seconds before retry {attempt + 1}/{max_retries}...")
                        time.sleep(retry_seconds)
                        continue
                    else:
                        print(f"\n❌ Rate limit error after {max_retries} attempts:")
                        print(f"   {error_msg}")
                        print("\n💡 Suggestions:")
                        print("   1. Wait a few minutes before trying again (free tier: 5 requests/minute)")
                        print("   2. Consider using a different model (gemini-2.0-flash-lite has higher limits)")
                        print("   3. Check your usage at: https://ai.dev/usage?tab=rate-limit")
                        sys.exit(1)
                else:
                    # Not a rate limit error, raise it
                    raise
        
        # If we get here, all retries failed
        raise Exception("Failed after all retries")
        
    except Exception as e:
        error_msg = str(e)
        print(f"\nError calling Gemini API: {error_msg}")
        
        # Provide helpful suggestions
        if "404" in error_msg or "not found" in error_msg.lower():
            print("\nTroubleshooting:")
            print("1. The model name might be incorrect. Try specifying a model with --model")
            print("2. Common model names: gemini-pro, gemini-1.5-pro-latest, gemini-1.5-flash")
            print("3. Check your API key is valid and has access to Gemini models")
            print("\nTo see available models, you can run:")
            print("  python -c \"import google.generativeai as genai; genai.configure(api_key='YOUR_KEY'); [print(m.name) for m in genai.list_models()]\"")
        
        sys.exit(1)


def save_tailored_cv(cv_text: str, output_path: str, hyperlinks: dict = None, formatting_info: dict = None):
    """
    Save tailored CV to PDF file
    
    Args:
        cv_text: Tailored CV text
        output_path: Path to save the output PDF file
        hyperlinks: Dictionary of hyperlinks to preserve (optional)
        formatting_info: Dictionary of formatting information to preserve (optional)
    """
    try:
        output_path = Path(output_path)
        
        # Ensure output is PDF
        if output_path.suffix.lower() != '.pdf':
            output_path = output_path.with_suffix('.pdf')
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if HAS_REPORTLAB:
            # Create PDF using ReportLab
            _create_pdf_from_text(cv_text, str(output_path), hyperlinks or {}, formatting_info or {})
        else:
            # Fallback: save as text file
            print("Warning: ReportLab not available. Saving as text file instead.")
            print("Install reportlab with: pip install reportlab")
            text_path = output_path.with_suffix('.txt')
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(cv_text)
            output_path = text_path
        
        print(f"\n✓ Tailored CV saved to: {output_path}")
    except Exception as e:
        print(f"Error saving output file: {e}")
        sys.exit(1)


def _create_pdf_from_text(cv_text: str, output_path: str, hyperlinks: dict = None, formatting_info: dict = None):
    """
    Create a nicely formatted PDF from CV text with hyperlinks and formatting
    
    Args:
        cv_text: CV text content (may contain HTML-like formatting markers)
        output_path: Path to save PDF
        hyperlinks: Dictionary of hyperlinks to preserve
        formatting_info: Dictionary of formatting information to preserve
    """
    if hyperlinks is None:
        hyperlinks = {}
    if formatting_info is None:
        formatting_info = {}
    # Create PDF document
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Create styles
    styles = getSampleStyleSheet()
    
    # Title style (for name at top)
    title_style = ParagraphStyle(
        'CVTitle',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=15,
        fontName='Helvetica-Bold'
    )
    
    # Section heading style
    heading_style = ParagraphStyle(
        'CVHeading',
        parent=styles['Heading2'],
        fontSize=14,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=10,
        spaceBefore=15,
        fontName='Helvetica-Bold',
        borderWidth=0,
        borderPadding=0,
        leftIndent=0
    )
    
    # Normal text style
    normal_style = ParagraphStyle(
        'CVNormal',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_LEFT,
        textColor=colors.black,
        spaceAfter=8,
        fontName='Helvetica',
        leading=14
    )
    
    # Bullet point style
    bullet_style = ParagraphStyle(
        'CVBullet',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_LEFT,
        textColor=colors.black,
        spaceAfter=6,
        fontName='Helvetica',
        leading=14,
        leftIndent=20
    )
    
    # Build content
    story = []
    
    # Parse and format the CV text
    lines = cv_text.split('\n')
    current_section = None
    in_paragraph = False
    paragraph_lines = []
    paragraph_indent = 0  # Track indentation for current paragraph
    
    def flush_paragraph():
        """Flush accumulated paragraph lines with hyperlink and formatting support"""
        nonlocal paragraph_lines, in_paragraph, paragraph_indent
        if paragraph_lines:
            paragraph_text = ' '.join(paragraph_lines)
            # Process formatting and hyperlinks
            paragraph_text = _process_formatting_and_hyperlinks(paragraph_text, hyperlinks)
            
            # Create style with indentation if needed
            if paragraph_indent > 0:
                indented_style = ParagraphStyle(
                    'CVIndented',
                    parent=normal_style,
                    leftIndent=paragraph_indent
                )
                story.append(Paragraph(paragraph_text, indented_style))
            else:
                story.append(Paragraph(paragraph_text, normal_style))
            paragraph_lines = []
            paragraph_indent = 0
            in_paragraph = False
    
    def detect_indentation(line):
        """Detect indentation level from line content"""
        # Check for indentation markers from extraction (remove them from line)
        indent_match = re.match(r'__INDENT_(\d+)__\s*', line)
        if indent_match:
            # Remove the marker from the line
            line = line.replace(indent_match.group(0), '', 1)
            return int(indent_match.group(1))
        
        # Detect based on leading spaces/tabs
        leading_spaces = len(line) - len(line.lstrip(' '))
        leading_tabs = len(line) - len(line.lstrip('\t'))
        if leading_tabs > 0:
            return leading_tabs * 20  # 20 points per tab
        elif leading_spaces > 0:
            # Assume 4 spaces = 1 indent level (20 points)
            return (leading_spaces // 4) * 20
        
        # Detect nested bullet points (multiple levels)
        if line.startswith('  •') or line.startswith('  -') or line.startswith('  *'):
            return 40  # Second level indent
        elif line.startswith('    •') or line.startswith('    -') or line.startswith('    *'):
            return 60  # Third level indent
        
        return 0
    
    for i, line in enumerate(lines):
        original_line = line  # Keep original for indentation detection
        # Detect indentation from original line (before cleaning)
        indent = detect_indentation(original_line)
        # Remove indentation markers before processing
        line = re.sub(r'__INDENT_\d+__\s*', '', line)
        line = line.strip()
        
        # Skip empty lines but add spacing
        if not line:
            flush_paragraph()
            if i < len(lines) - 1:  # Don't add space at the end
                story.append(Spacer(1, 6))
            continue
        
        # Detect section headings (lines that are all caps, short, or end with colon)
        is_heading = (
            (line.isupper() and len(line) < 60 and len(line) > 2)
            or (line.endswith(':') and len(line) < 60)
            or (re.match(r'^[A-Z][A-Z\s&]+$', line) and len(line) < 60)
            or (re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*:?$', line) and len(line) < 40)  # Title Case headings
        )
        
        if is_heading:
            flush_paragraph()
            # Add spacing before new section
            if current_section:
                story.append(Spacer(1, 12))
            heading_text = line.replace(':', '').strip()
            heading_text = _process_formatting_and_hyperlinks(heading_text, hyperlinks)
            story.append(Paragraph(heading_text, heading_style))
            current_section = line
        else:
            # Regular content
            # Check if it's a bullet point
            if line.startswith('•') or line.startswith('-') or line.startswith('*') or line.startswith('·'):
                flush_paragraph()
                content = line.lstrip('•-*· ').strip()
                content = _process_formatting_and_hyperlinks(content, hyperlinks)
                # Apply indentation to bullet style
                if indent > 0:
                    indented_bullet_style = ParagraphStyle(
                        'CVIndentedBullet',
                        parent=bullet_style,
                        leftIndent=indent
                    )
                    story.append(Paragraph(content, indented_bullet_style))
                else:
                    story.append(Paragraph(content, bullet_style))
            elif re.match(r'^\d+[\.\)]\s+', line):  # Numbered list
                flush_paragraph()
                line = _process_formatting_and_hyperlinks(line, hyperlinks)
                # Apply indentation to numbered list
                if indent > 0:
                    indented_bullet_style = ParagraphStyle(
                        'CVIndentedBullet',
                        parent=bullet_style,
                        leftIndent=indent
                    )
                    story.append(Paragraph(line, indented_bullet_style))
                else:
                    story.append(Paragraph(line, bullet_style))
            else:
                # Regular paragraph - accumulate lines with same indentation
                if in_paragraph and indent != paragraph_indent:
                    # Different indentation, flush previous paragraph
                    flush_paragraph()
                if not in_paragraph:
                    paragraph_indent = indent
                paragraph_lines.append(line)
                in_paragraph = True
    
    # Flush any remaining paragraph
    flush_paragraph()
    
    # Generate PDF
    doc.build(story)


def _escape_html(text: str) -> str:
    """
    Escape HTML special characters for ReportLab
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text
    """
    # ReportLab uses XML-style escaping
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def _process_formatting_and_hyperlinks(text: str, hyperlinks: dict) -> str:
    """
    Process formatting and hyperlinks in text
    
    Args:
        text: Text that may contain formatting markers and hyperlinks
        hyperlinks: Dictionary of known hyperlinks from original PDF
        
    Returns:
        Text with ReportLab formatting and hyperlink markup
    """
    # First, escape any unescaped HTML/XML characters (but preserve our formatting tags)
    # We need to be careful not to escape our formatting tags
    
    # Process formatting tags first (before escaping)
    # ReportLab supports: <b>, <i>, <u>, <font>, <link>
    # Our tags: <b>, <i>, <font color="...">, <font size="...">
    
    # Convert our formatting tags to ReportLab format if needed
    # <b>text</b> -> <b>text</b> (already correct)
    # <i>text</i> -> <i>text</i> (already correct)
    # <font color="#hex">text</font> -> <font color="#hex">text</font> (already correct)
    # <font size="12">text</font> -> <font size="12">text</font> (ReportLab uses fontSize)
    
    # Helper function to escape URL for use in XML/HTML attributes
    def escape_url(url: str) -> str:
        """Escape URL for use in href attribute"""
        return url.replace('&', '&amp;').replace('"', '&quot;')
    
    # Helper function to check if a position is inside a tag
    def is_inside_tag(text: str, pos: int) -> bool:
        """Check if position is inside an XML/HTML tag"""
        before = text[:pos]
        after = text[pos:]
        
        # Find the last < and > before this position
        last_open = before.rfind('<')
        last_close = before.rfind('>')
        
        # If there's an unclosed < tag, we're inside a tag
        if last_open > last_close:
            return True
        
        # Check if we're inside quotes (attribute value)
        last_quote = before.rfind('"')
        if last_quote > last_close:
            # Check if there's a matching closing quote after
            next_quote = after.find('"')
            if next_quote != -1:
                return True
        
        return False
    
    # First, mark all existing link tags to avoid processing URLs inside them
    # Replace existing link tags with placeholders (including nested content)
    link_placeholders = {}
    placeholder_counter = 0
    
    def replace_existing_link(match):
        nonlocal placeholder_counter
        placeholder = f"__LINK_PLACEHOLDER_{placeholder_counter}__"
        # Store the full link tag including content
        full_link = match.group(0)
        link_placeholders[placeholder] = full_link
        placeholder_counter += 1
        return placeholder
    
    # Remove existing link tags temporarily (non-greedy to avoid matching nested links)
    # Match: <link...>content</link> but be careful with nested tags
    text = re.sub(r'<link[^>]*>.*?</link>', replace_existing_link, text, flags=re.DOTALL)
    
    # Also handle self-closing or malformed link tags
    text = re.sub(r'<link[^>]*/>', replace_existing_link, text)
    
    # Convert font size tags to ReportLab format
    def replace_font_size(match):
        size = match.group(1)
        content = match.group(2)
        return f'<font size="{size}">{content}</font>'
    
    text = re.sub(r'<font size="(\d+)">(.*?)</font>', replace_font_size, text, flags=re.DOTALL)
    
    # Process markdown-style links [text](url) - but only if not already a link
    def replace_markdown_link(match):
        link_text = match.group(1)
        url = match.group(2)
        escaped_url = escape_url(url)
        # Escape the link text content
        escaped_text = link_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<link href="{escaped_url}"><u><font color="blue">{escaped_text}</font></u></link>'
    
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_markdown_link, text)
    
    # Process plain URLs (http:// or https://) - but not if they're already in tags
    def replace_plain_url(match):
        url = match.group(0)
        pos = match.start()
        
        # Skip if inside a tag or placeholder
        if is_inside_tag(text, pos):
            return url
        
        # Check if we're inside a placeholder (which represents an existing link)
        for placeholder in link_placeholders.keys():
            placeholder_pos = text.find(placeholder)
            if placeholder_pos != -1 and placeholder_pos <= pos < placeholder_pos + len(placeholder):
                return url
        
        # Also check if there's an unclosed <link tag before this
        before = text[:pos]
        link_open_count = len(re.findall(r'<link[^>]*>', before))
        link_close_count = len(re.findall(r'</link>', before))
        if link_open_count > link_close_count:
            return url
        
        # Safe to process - escape the URL
        escaped_url = escape_url(url)
        escaped_text = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<link href="{escaped_url}"><u><font color="blue">{escaped_text}</font></u></link>'
    
    text = re.sub(r'https?://[^\s<>"{}|\\^`\[\]]+', replace_plain_url, text)
    
    # Restore original link tags
    for placeholder, original_link in link_placeholders.items():
        text = text.replace(placeholder, original_link)
    
    # Now escape HTML characters that are not part of our tags
    text = _escape_html_preserving_tags(text)
    
    return text


def _escape_html_preserving_tags(text: str) -> str:
    """
    Escape HTML special characters while preserving formatting tags
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text with formatting tags preserved
    """
    # First check if text is already double-escaped (contains &amp;lt; or &amp;gt;)
    # If so, return as-is to avoid further escaping
    if '&amp;lt;' in text or '&amp;gt;' in text:
        return text
    
    # Split by tags, escape content between tags
    # Match both opening and closing tags: <tag> or </tag> or <tag attr="value">
    parts = re.split(r'(</?[a-zA-Z][^>]*>)', text)
    result = []
    
    for part in parts:
        if part.startswith('<') and part.endswith('>'):
            # This is a tag - validate it's a proper XML/HTML tag
            # More flexible regex to handle various attribute formats
            # Matches: <tag>, </tag>, <tag attr="value">, <tag attr='value'>, <tag attr=value>
            tag_match = re.match(r'^</?[a-zA-Z][a-zA-Z0-9]*(?:\s+[^>]*)?>$', part)
            if tag_match:
                # Valid tag structure - keep it as-is (URLs in href should already be escaped)
                result.append(part)
            else:
                # Check if it's already escaped (contains &lt; or &gt;)
                if '&lt;' in part or '&gt;' in part or '&amp;' in part:
                    # Already escaped, keep as-is
                    result.append(part)
                else:
                    # Invalid tag format, escape the whole thing
                    escaped = part.replace('&', '&amp;')
                    escaped = escaped.replace('<', '&lt;')
                    escaped = escaped.replace('>', '&gt;')
                    result.append(escaped)
        else:
            # This is content between tags
            # Check if it's already escaped
            if '&lt;' in part or '&gt;' in part or '&amp;' in part:
                # Already escaped, keep as-is (don't double-escape)
                result.append(part)
            else:
                # Has unescaped content - escape it
                if '<' in part or '>' in part:
                    # Has unescaped tags, escape them
                    escaped = part.replace('&', '&amp;')
                    escaped = escaped.replace('<', '&lt;')
                    escaped = escaped.replace('>', '&gt;')
                    result.append(escaped)
                else:
                    # No tags, just escape &
                    escaped = part.replace('&', '&amp;')
                    result.append(escaped)
    
    return ''.join(result)


def main():
    parser = argparse.ArgumentParser(
        description='Tailor your CV for a specific job using Google Gemini AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tailor_cv_with_gemini.py --job-url "https://example.com/job" --cv "my_cv.pdf" --api-key "YOUR_API_KEY"
  python tailor_cv_with_gemini.py --job-url "https://example.com/job" --cv "my_cv.pdf" --api-key "YOUR_API_KEY" --output "tailored_cv.pdf"
  python tailor_cv_with_gemini.py --job-url "https://example.com/job" --cv "my_cv.pdf" --api-key "YOUR_API_KEY" --model "gemini-pro"
        """
    )
    
    parser.add_argument(
        '--job-url',
        type=str,
        required=True,
        help='URL of the job description'
    )
    
    parser.add_argument(
        '--cv',
        type=str,
        required=True,
        help='Path to your CV PDF file'
    )
    
    parser.add_argument(
        '--api-key',
        type=str,
        required=False,
        help='Google Gemini API key (or set GEMINI_API_KEY environment variable)'
    )
        
    parser.add_argument(
        '--model',
        type=str,
        #default='gemini-pro',
        help='Gemini model name to use (e.g., gemini-pro, gemini-1.5-pro-latest). If not specified, will auto-detect.'
    )

    parser.add_argument(
        '--tag',
        type=str,
        default='tag',
        help='Tag to use when Output file path is missing'
    )

    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output file path for the tailored CV PDF (default: tailored_cv_{tag}.pdf)'
    )

    args = parser.parse_args()

    if not args.output:
        args.output = f'tailored_cv_{args.tag}.pdf'

    # Get API key from argument or environment variable
    api_key = args.api_key or os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("Error: Gemini API key is required.")
        print("Provide it via --api-key argument or set GEMINI_API_KEY environment variable")
        sys.exit(1)
    
    print("=" * 60)
    print("CV Tailoring with Google Gemini")
    print("=" * 60)
    print()
    
    # Step 1: Fetch job description
    print("Step 1: Fetching job description from URL...")
    job_description = fetch_job_description(args.job_url)
    print(f"✓ Job description fetched ({len(job_description)} characters)")
    print()
    
    # Step 2: Extract text, hyperlinks, and formatting from CV PDF
    print("Step 2: Reading CV PDF file...")
    cv_text, hyperlinks, formatting_info = extract_text_from_pdf(args.cv)
    print(f"✓ CV extracted ({len(cv_text)} characters)")
    if hyperlinks:
        print(f"✓ Found {len(hyperlinks)} hyperlink(s) to preserve")
    if formatting_info:
        print(f"✓ Found formatting information to preserve")
    print()
    
    # Step 3: Tailor CV with Gemini
    print("Step 3: Tailoring CV with Gemini AI...")
    tailored_cv = tailor_cv_with_gemini(job_description, cv_text, api_key, args.model)
    print("✓ CV tailored successfully")
    print()
    
    # Step 4: Save output
    print("Step 4: Saving tailored CV...")
    save_tailored_cv(tailored_cv, args.output, hyperlinks, formatting_info)
    print()
    
    print("=" * 60)
    print("Process completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()

