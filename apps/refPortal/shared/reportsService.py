"""
PDF Report Service for RefereeX
Handles server-side PDF generation for game reports
"""

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import tempfile
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class ReportsService:
    def __init__(self, logger: Logger):
        self.logger = logger
        
        # Initialize ReportLab styles
        self.styles = getSampleStyleSheet()
        self._setup_hebrew_styles()
        
        # Set up logo paths
        self._setup_logo_paths()
        
    def _setup_hebrew_styles(self):
        """Setup Hebrew-compatible styles for ReportLab"""
        # Register Hebrew fonts
        self._register_hebrew_fonts()
        
        # Create custom styles for Hebrew text using dynamic font names
        self.hebrew_title_style = ParagraphStyle(
            'HebrewTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            alignment=TA_CENTER,
            textColor=colors.white,
            spaceAfter=20,
            fontName=self.hebrew_bold_font_name
        )
        
        self.hebrew_heading_style = ParagraphStyle(
            'HebrewHeading',
            parent=self.styles['Heading2'],
            fontSize=18,
            alignment=TA_RIGHT,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=15,
            spaceBefore=20,
            fontName=self.hebrew_bold_font_name
        )
        
        self.hebrew_normal_style = ParagraphStyle(
            'HebrewNormal',
            parent=self.styles['Normal'],
            fontSize=12,
            alignment=TA_RIGHT,
            textColor=colors.black,
            spaceAfter=10,
            fontName=self.hebrew_font_name
        )
        
        self.hebrew_table_header_style = ParagraphStyle(
            'HebrewTableHeader',
            parent=self.styles['Normal'],
            fontSize=12,
            alignment=TA_RIGHT,
            textColor=colors.white,
            fontName=self.hebrew_bold_font_name
        )
        
        self.hebrew_table_cell_style = ParagraphStyle(
            'HebrewTableCell',
            parent=self.styles['Normal'],
            fontSize=11,
            alignment=TA_RIGHT,
            textColor=colors.black,
            fontName=self.hebrew_font_name
        )
    
    def _register_hebrew_fonts(self):
        """Register Hebrew fonts for ReportLab"""
        try:
            # Try to register system Hebrew fonts
            # Common Hebrew fonts on different systems
            hebrew_fonts = [
                # Environment variable font path
                os.getenv('fontPath'),
                '/System/Library/Fonts/SFHebrew.ttf',
                '/System/Library/Fonts/Helvetica.ttc',
                '/System/Library/Fonts/Arial.ttf',
                '/System/Library/Fonts/HelveticaNeue.ttc',
                '/System/Library/Fonts/HelveticaNeue.dfont',
                '/Library/Fonts/Arial.ttf',
                '/Library/Fonts/Helvetica.ttc',
                # Windows Hebrew fonts
                'C:/Windows/Fonts/arial.ttf',
                'C:/Windows/Fonts/calibri.ttf',
                'C:/Windows/Fonts/arialbd.ttf',
                'C:/Windows/Fonts/calibrib.ttf',
                'C:/Windows/Fonts/tahoma.ttf',
                'C:/Windows/Fonts/tahomabd.ttf',
                # Linux Hebrew fonts
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
                '/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf',
                # Additional common fonts
                '/usr/share/fonts/truetype/arphic/ukai.ttf',
                '/usr/share/fonts/truetype/arphic/uming.ttf',
            ]
            
            hebrew_bold_fonts = [
                # Environment variable font path
                os.getenv('fontPath'),
                '/System/Library/Fonts/Helvetica.ttc',
                '/System/Library/Fonts/Arial.ttf',
                '/System/Library/Fonts/HelveticaNeue.ttc',
                '/System/Library/Fonts/HelveticaNeue.dfont',
                '/Library/Fonts/Arial.ttf',
                '/Library/Fonts/Helvetica.ttc',
                # Windows Hebrew fonts
                'C:/Windows/Fonts/arialbd.ttf',
                'C:/Windows/Fonts/calibrib.ttf',
                'C:/Windows/Fonts/tahomabd.ttf',
                # Linux Hebrew fonts
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf',
                '/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf',
            ]
            
            # Try to find and register a Hebrew-compatible font
            hebrew_font_found = False
            hebrew_bold_font_found = False
            
            for font_path in hebrew_fonts:
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont('Hebrew', font_path))
                        hebrew_font_found = True
                        self.logger.info(f'Registered Hebrew font: {font_path}')
                        break
                    except Exception as e:
                        self.logger.warning(f'Failed to register font {font_path}: {e}')
                        continue
            
            for font_path in hebrew_bold_fonts:
                if os.path.exists(font_path):
                    try:
                        pdfmetrics.registerFont(TTFont('Hebrew-Bold', font_path))
                        hebrew_bold_font_found = True
                        self.logger.info(f'Registered Hebrew-Bold font: {font_path}')
                        break
                    except Exception as e:
                        self.logger.warning(f'Failed to register bold font {font_path}: {e}')
                        continue
            
            # Fallback to built-in fonts if no Hebrew fonts found
            if not hebrew_font_found:
                self.logger.warning('No Hebrew fonts found, using fallback')
                # Use a fallback approach with better Unicode support
                self.hebrew_font_name = 'Helvetica'
                self.hebrew_bold_font_name = 'Helvetica-Bold'
            else:
                self.hebrew_font_name = 'Hebrew'
                self.hebrew_bold_font_name = 'Hebrew-Bold' if hebrew_bold_font_found else 'Hebrew'
                
        except Exception as e:
            self.logger.error(f'Error setting up Hebrew fonts: {e}')
            # Fallback to basic fonts
            self.hebrew_font_name = 'Helvetica'
            self.hebrew_bold_font_name = 'Helvetica-Bold'
        
        self.hebrew_footer_style = ParagraphStyle(
            'HebrewFooter',
            parent=self.styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#666666'),
            spaceAfter=5,
            fontName=self.hebrew_font_name
        )
    
    def _prepare_hebrew_text(self, text: str) -> str:
        """Prepare Hebrew text for better rendering in ReportLab"""
        if not text:
            return text
        
        # Ensure text is properly encoded
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        
        # Add some basic Hebrew text direction hints
        # This helps with better text flow in PDF
        text = text.replace('\n', '<br/>')
        
        return text

    def _setup_logo_paths(self):
        """Setup paths to logo files and HTTP URLs"""
        try:
            # Get the project root directory
            project_root = Path(__file__).resolve().parent.parent
            images_dir = project_root / 'rpApi' / 'static' / 'images'
            
            # Set logo paths
            self.refereex_logo_path = images_dir / 'RefereeX.png'
            self.ifa_logo_path = images_dir / 'the-israel-football-association-logo.png'
            
            # Check if logos exist
            self.refereex_logo_exists = self.refereex_logo_path.exists()
            self.ifa_logo_exists = self.ifa_logo_path.exists()
            
            # Set up HTTP URLs for email HTML
            self.base_url = os.getenv('docsServiceUrlBase', 'https://refereex.com/docs')
            self.refereex_logo_url = f"{self.base_url}/images/RefereeX.png"
            self.ifa_logo_url = f"{self.base_url}/images/the-israel-football-association-logo.png"
            
            if not self.refereex_logo_exists:
                self.logger.warning(f"RefereeX logo not found at: {self.refereex_logo_path}")
            if not self.ifa_logo_exists:
                self.logger.warning(f"IFA logo not found at: {self.ifa_logo_path}")
                
        except Exception as e:
            self.logger.error(f"Error setting up logo paths: {str(e)}")
            self.refereex_logo_exists = False
            self.ifa_logo_exists = False

    def generate_pdf(self, report_data: Dict[str, Any]) -> bytes:
        """
        Generate PDF report from report data using ReportLab only
        
        Args:
            report_data: Dictionary containing report information
            
        Returns:
            PDF content as bytes
        """
        try:
            # Create a BytesIO buffer to hold the PDF
            buffer = io.BytesIO()
            
            # Create PDF document
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=2*cm,
                leftMargin=2*cm,
                topMargin=2*cm,
                bottomMargin=2*cm
            )
            
            # Build the PDF content
            story = self._build_pdf_content(report_data)
            
            # Generate PDF
            doc.build(story)
            
            # Get PDF bytes
            pdf_bytes = buffer.getvalue()
            buffer.close()
            
            self.logger.info(f'PDF generated successfully for game {report_data.get("gameId", "unknown")}')
            return pdf_bytes
            
        except Exception as ex:
            self.logger.error(f'Failed to generate PDF: {str(ex)}')
            raise

    def generate_html(self, report_data: Dict[str, Any]) -> str:
        """
        Generate HTML report from report data
        
        Args:
            report_data: Dictionary containing report information
            
        Returns:
            HTML content as string
        """
        try:
            # Format game details
            game_title = report_data.get('gameTitle', 'משחק לא ידוע')
            game_url = report_data.get('gameUrl')
            game_date = report_data.get('gameDate', 'לא ידוע')
            game_time = report_data.get('gameTime', 'לא ידוע')
            league = report_data.get('league', 'לא ידוע')
            field = report_data.get('field', 'לא ידוע')
            report_datetime = report_data.get('reportDatetime', 'לא ידוע')
            reporter = report_data.get('reporter', 'לא ידוע')
            categories = report_data.get('categories', [])
            details = report_data.get('details', 'אין פרטים נוספים')
            game_id = report_data.get('gameId', 'לא ידוע')
            
            # Create status badge
            status_class = 'status-pending'
            
            # Create categories HTML
            categories_html = self._create_categories_html(categories)
            
            # Create details HTML
            details_html = self._create_details_html(details)
            
            # Get current timestamp for footer
            current_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            
            html_content = f"""
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>דו״ח תיקון משחק - {game_title}</title>
    <style>
        {self._get_html_styles()}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="logo-section">
                {self._get_logo_html()}
            </div>
            <div class="title-section">
                <h1>דו״ח תיקון משחק</h1>
                <div class="game-id">משחק #{game_id}</div>
            </div>
        </div>
    </div>
    
    <div class="content">
        <div class="section">
            <h2>פרטי המשחק</h2>
            <table class="info-table">
                <tbody>
                    <tr>
                        <td>משחק</td>
                        <td><a href="{game_url if game_url else '#'}" target="_blank">{game_title}</a></td>
                    </tr>
                    <tr>
                        <td>תאריך</td>
                        <td>{game_date}</td>
                    </tr>
                    <tr>
                        <td>שעה</td>
                        <td>{game_time}</td>
                    </tr>
                    <tr>
                        <td>ליגה</td>
                        <td>{league}</td>
                    </tr>
                    <tr>
                        <td>מגרש</td>
                        <td>{field}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>פרטי הדו״ח</h2>
            <table class="info-table">
                <thead>
                    <tr>
                        <th>שדה</th>
                        <th>ערך</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>תאריך יצירת הדו״ח</td>
                        <td>{report_datetime}</td>
                    </tr>
                    <tr>
                        <td>מדווח</td>
                        <td>{reporter}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>קטגוריות שנבחרו</h2>
            {categories_html}
        </div>
        
        <div class="section">
            <h2>פרטים נוספים</h2>
            <div class="details-section">
                {details_html}
            </div>
        </div>
    </div>
    
    <div class="footer">
        <p>דו״ח זה נוצר אוטומטית על ידי מערכת RefereeX</p>
        <div class="timestamp">נוצר ב: {current_time}</div>
    </div>
</body>
</html>
            """.strip()
            
            self.logger.info(f'HTML report generated successfully for game {game_id}')
            return html_content
            
        except Exception as ex:
            self.logger.error(f'Failed to generate HTML report: {str(ex)}')
            raise

    def _build_pdf_content(self, report_data: Dict[str, Any]) -> list:
        """Build PDF content using ReportLab elements"""
        story = []
        
        # Format game details
        game_title = report_data.get('gameTitle', 'משחק לא ידוע')
        game_date = report_data.get('gameDate', 'לא ידוע')
        game_time = report_data.get('gameTime', 'לא ידוע')
        league = report_data.get('league', 'לא ידוע')
        field = report_data.get('field', 'לא ידוע')
        role = report_data.get('role', 'לא ידוע')
        status = report_data.get('status', 'לא ידוע')
        report_datetime = report_data.get('reportDatetime', 'לא ידוע')
        reporter = report_data.get('reporter', 'לא ידוע')
        categories = report_data.get('categories', [])
        details = report_data.get('details', 'אין פרטים נוספים')
        game_id = report_data.get('gameId', 'לא ידוע')
        
        # Header with background
        story.append(self._create_header_section(game_id))
        story.append(Spacer(1, 20))
        
        # Game Details Section
        story.append(Paragraph(text=self._prepare_hebrew_text("פרטי המשחק"), style=self.hebrew_heading_style))
        
        game_data = [
            ['שדה', 'ערך'],
            ['משחק', game_title],
            ['תאריך', game_date],
            ['שעה', game_time],
            ['ליגה', league],
            ['מגרש', field],
            ['תפקיד', role],
            ['סטטוס', status]
        ]
        
        game_table = Table(game_data, colWidths=[4*cm, 8*cm])
        game_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')])
        ]))
        
        story.append(game_table)
        story.append(Spacer(1, 20))
        
        # Report Details Section
        story.append(Paragraph(text=self._prepare_hebrew_text("פרטי הדו״ח"), style=self.hebrew_heading_style))
        
        report_data_table = [
            ['שדה', 'ערך'],
            ['תאריך יצירת הדו״ח', report_datetime],
            ['מדווח', reporter]
        ]
        
        report_table = Table(report_data_table, colWidths=[4*cm, 8*cm])
        report_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')])
        ]))
        
        story.append(report_table)
        story.append(Spacer(1, 20))
        
        # Categories Section
        story.append(Paragraph(text=self._prepare_hebrew_text("קטגוריות שנבחרו"), style=self.hebrew_heading_style))
        
        if categories:
            # Handle both list and dictionary types for categories
            if isinstance(categories, dict):
                for key, value in categories.items():
                    if value:  # Only include non-empty values
                        story.append(Paragraph(text=self._prepare_hebrew_text(f"• {key}: {value}"), style=self.hebrew_normal_style))
            elif isinstance(categories, list):
                for category in categories:
                    story.append(Paragraph(text=self._prepare_hebrew_text(f"• {category}"), style=self.hebrew_normal_style))
            else:
                story.append(Paragraph(text=self._prepare_hebrew_text(f"• {str(categories)}"), style=self.hebrew_normal_style))
        else:
            story.append(Paragraph(text=self._prepare_hebrew_text("אין קטגוריות"), style=self.hebrew_normal_style))
        
        story.append(Spacer(1, 20))
        
        # Details Section
        story.append(Paragraph(text=self._prepare_hebrew_text("פרטים נוספים"), style=self.hebrew_heading_style))
        
        # Convert details dictionary to string format
        if isinstance(details, dict):
            details_text = ""
            for key, value in details.items():
                if value:  # Only include non-empty values
                    details_text += f"{key}: {value}\n"
            details_text = details_text.strip() or "אין פרטים נוספים"
        else:
            details_text = str(details) if details else "אין פרטים נוספים"
        
        story.append(Paragraph(text=self._prepare_hebrew_text(details_text), style=self.hebrew_normal_style))
        story.append(Spacer(1, 30))
        
        # Footer
        current_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        story.append(Paragraph(text=self._prepare_hebrew_text("דו״ח זה נוצר אוטומטית על ידי מערכת RefereeX"), style=self.hebrew_footer_style))
        story.append(Paragraph(text=self._prepare_hebrew_text(f"נוצר ב: {current_time}"), style=self.hebrew_footer_style))
        
        return story

    def _create_header_section(self, game_id: str) -> Table:
        """Create a header section with logos and background color"""
        # Create logo elements
        logo_elements = []
        
        # Add RefereeX logo if available
        if self.refereex_logo_exists:
            try:
                refereex_logo = Image(str(self.refereex_logo_path), width=2*cm, height=2*cm)
                logo_elements.append(refereex_logo)
            except Exception as e:
                self.logger.warning(f"Could not load RefereeX logo:", e)
        
        # Add IFA logo if available
        if self.ifa_logo_exists:
            try:
                ifa_logo = Image(str(self.ifa_logo_path), width=2*cm, height=2*cm)
                logo_elements.append(ifa_logo)
            except Exception as e:
                self.logger.warning(f"Could not load IFA logo:", e)
        
        # Create header data with logos
        if logo_elements:
            # Create a table with logos and title
            header_data = [
                [logo_elements[0] if len(logo_elements) > 0 else '', 
                 self._prepare_hebrew_text('דו״ח תיקון משחק'),
                 logo_elements[1] if len(logo_elements) > 1 else ''],
                ['', self._prepare_hebrew_text(f'משחק #{game_id}'), '']
            ]
            col_widths = [2*cm, 8*cm, 2*cm]
        else:
            # Fallback to simple header without logos
            header_data = [
                [self._prepare_hebrew_text('דו״ח תיקון משחק')],
                [self._prepare_hebrew_text(f'משחק #{game_id}')]
            ]
            col_widths = [12*cm]
        
        header_table = Table(header_data, colWidths=col_widths)
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (0, 0), 24),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (0, 1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 15),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        
        return header_table

    def generate_pdf_to_file(self, report_data: Dict[str, Any], file_path: str) -> str:
        """
        Generate PDF and save to file
        
        Args:
            report_data: Dictionary containing report information
            file_path: Path where to save the PDF file
            
        Returns:
            Path to the generated PDF file
        """
        try:
            pdf_bytes = self.generate_pdf(report_data)
            
            # Ensure directory exists
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Write PDF to file
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)
            
            self.logger.info(f'PDF saved to file: {file_path}')
            return file_path
            
        except Exception as e:
            self.logger.error(f'Failed to save PDF to file {file_path}: {str(e)}')
            raise

    def generate_pdf_to_temp_file(self, report_data: Dict[str, Any]) -> str:
        """
        Generate PDF and save to temporary file
        
        Args:
            report_data: Dictionary containing report information
            
        Returns:
            Path to the temporary PDF file
        """
        try:
            # Create temporary file
            temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix='game_report_')
            os.close(temp_fd)  # Close the file descriptor, we'll use the path
            
            return self.generate_pdf_to_file(report_data, temp_path)
            
        except Exception as e:
            self.logger.error(f'Failed to create temporary PDF file: {str(e)}')
            raise

    def _get_html_styles(self) -> str:
        """Get CSS styles for HTML report"""
        return """
        @page {
            size: A4;
            margin: 2cm;
            direction: rtl;
        }
        
        body {
            font-family: 'Arial', 'Helvetica', sans-serif;
            direction: rtl;
            text-align: right;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 0;
            background-color: #f8f9fa;
        }
        
        .header {
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            border-radius: 5px 5px 0 0;
            margin-bottom: 20px;
        }
        
        .header-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            max-width: 100%;
        }
        
        .logo-section {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .logo-section img {
            height: 60px;
            width: auto;
            max-width: 80px;
            object-fit: contain;
        }
        
        .title-section {
            text-align: center;
            flex: 1;
        }
        
        .title-section h1 {
            margin: 0;
            font-size: 24px;
        }
        
        .content {
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 0 0 5px 5px;
        }
        
        .section {
            margin-bottom: 25px;
            page-break-inside: avoid;
        }
        
        .section h2 {
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
            margin-bottom: 15px;
            font-size: 18px;
        }
        
        .section h3 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 16px;
        }
        
        .info-table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background-color: white;
            border-radius: 5px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .info-table th {
            background-color: #34495e;
            color: white;
            padding: 12px;
            text-align: right;
            font-weight: bold;
        }
        
        .info-table td {
            padding: 12px;
            border-bottom: 1px solid #ddd;
            text-align: right;
        }
        
        .info-table tr:nth-child(even) {
            background-color: #f8f9fa;
        }
        
        .info-table tr:hover {
            background-color: #e8f4f8;
        }
        
        .categories {
            list-style-type: none;
            padding: 0;
            margin: 10px 0;
        }
        
        .categories li {
            background-color: #e8f4f8;
            margin: 8px 0;
            padding: 12px;
            border-radius: 5px;
            border-right: 4px solid #3498db;
            font-weight: 500;
        }
        
        .details-section {
            background-color: white;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
            margin: 15px 0;
        }
        
        .footer {
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #ecf0f1;
            color: #666;
            font-size: 14px;
        }
        
        .timestamp {
            color: #7f8c8d;
            font-size: 12px;
            margin-top: 10px;
        }
        
        .game-id {
            background-color: #3498db;
            color: white;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }
        
        .status-pending {
            background-color: #f39c12;
            color: white;
        }
        
        .status-completed {
            background-color: #27ae60;
            color: white;
        }
        
        .status-cancelled {
            background-color: #e74c3c;
            color: white;
        }
        
        @media print {
            .header {
                page-break-after: avoid;
            }
            
            .section {
                page-break-inside: avoid;
            }
        }
        """

    def _create_categories_html(self, categories) -> str:
        """Create HTML for categories section"""
        if not categories:
            return '<ul class="categories"><li>אין קטגוריות</li></ul>'
        
        if isinstance(categories, dict):
            items_html = ""
            for key, value in categories.items():
                if value:
                    items_html += f'<li>{key}: {value}</li>'
            return f'<ul class="categories">{items_html}</ul>'
        elif isinstance(categories, list):
            items_html = ""
            for category in categories:
                items_html += f'<li>{category}</li>'
            return f'<ul class="categories">{items_html}</ul>'
        else:
            return f'<ul class="categories"><li>{str(categories)}</li></ul>'

    def _create_details_html(self, details) -> str:
        """Create HTML for details section"""
        if isinstance(details, dict):
            details_html = ""
            for key, value in details.items():
                if value:
                    details_html += f'<p><strong>{key}:</strong> {value}</p>'
            return details_html or '<p>אין פרטים נוספים</p>'
        else:
            details_text = str(details) if details else "אין פרטים נוספים"
            return f'<p>{details_text}</p>'

    def _get_logo_html(self) -> str:
        """Generate HTML for logos using HTTP URLs"""
        logo_html = ""
        
        # Add RefereeX logo if available
        logo_html += f'<img src="{self.refereex_logo_url}" alt="RefereeX Logo" class="logo">'
        
        # Add IFA logo if available
        logo_html += f'<img src="{self.ifa_logo_url}" alt="IFA Logo" class="logo">'
        
        return logo_html

    def generate_html_for_email(self, report_data: Dict[str, Any]) -> str:
        """
        Generate HTML report for email use with HTTP URLs for images
        
        Args:
            report_data: Dictionary containing report information
            
        Returns:
            HTML content as string with HTTP URLs for images
        """
        try:
            # Format game details
            game_title = report_data.get('gameTitle', 'משחק לא ידוע')
            game_date = report_data.get('gameDate', 'לא ידוע')
            game_time = report_data.get('gameTime', 'לא ידוע')
            league = report_data.get('league', 'לא ידוע')
            field = report_data.get('field', 'לא ידוע')
            role = report_data.get('role', 'לא ידוע')
            status = report_data.get('status', 'לא ידוע')
            report_datetime = report_data.get('reportDatetime', 'לא ידוע')
            reporter = report_data.get('reporter', 'לא ידוע')
            categories = report_data.get('categories', [])
            details = report_data.get('details', 'אין פרטים נוספים')
            game_id = report_data.get('gameId', 'לא ידוע')
            
            # Create status badge
            status_class = 'status-pending'
            if status.lower() in ['completed', 'finished', 'סיום']:
                status_class = 'status-completed'
            elif status.lower() in ['cancelled', 'canceled', 'בוטל']:
                status_class = 'status-cancelled'
            
            # Create categories HTML
            categories_html = self._create_categories_html(categories)
            
            # Create details HTML
            details_html = self._create_details_html(details)
            
            # Get current timestamp for footer
            current_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            
            html_content = f"""
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>דו״ח תיקון משחק - {game_title}</title>
    <style>
        {self._get_html_styles()}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="logo-section">
                {self._get_logo_html()}
            </div>
            <div class="title-section">
                <h1>דו״ח תיקון משחק</h1>
                <div class="game-id">משחק #{game_id}</div>
            </div>
        </div>
    </div>
    
    <div class="content">
        <div class="section">
            <h2>פרטי המשחק</h2>
            <table class="info-table">
                <thead>
                    <tr>
                        <th>שדה</th>
                        <th>ערך</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>משחק</td>
                        <td>{game_title}</td>
                    </tr>
                    <tr>
                        <td>תאריך</td>
                        <td>{game_date}</td>
                    </tr>
                    <tr>
                        <td>שעה</td>
                        <td>{game_time}</td>
                    </tr>
                    <tr>
                        <td>ליגה</td>
                        <td>{league}</td>
                    </tr>
                    <tr>
                        <td>מגרש</td>
                        <td>{field}</td>
                    </tr>
                    <tr>
                        <td>תפקיד</td>
                        <td>{role}</td>
                    </tr>
                    <tr>
                        <td>סטטוס</td>
                        <td><span class="status-badge {status_class}">{status}</span></td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>פרטי הדו״ח</h2>
            <table class="info-table">
                <thead>
                    <tr>
                        <th>שדה</th>
                        <th>ערך</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>תאריך יצירת הדו״ח</td>
                        <td>{report_datetime}</td>
                    </tr>
                    <tr>
                        <td>מדווח</td>
                        <td>{reporter}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>קטגוריות שנבחרו</h2>
            {categories_html}
        </div>
        
        <div class="section">
            <h2>פרטים נוספים</h2>
            <div class="details-section">
                {details_html}
            </div>
        </div>
    </div>
    
    <div class="footer">
        <p>דו״ח זה נוצר אוטומטית על ידי מערכת RefereeX</p>
        <div class="timestamp">נוצר ב: {current_time}</div>
    </div>
</body>
</html>
            """.strip()
            
            self.logger.info(f'HTML email report generated successfully for game {game_id}')
            return html_content
            
        except Exception as ex:
            self.logger.error(f'Failed to generate HTML email report: {str(ex)}')
            raise
