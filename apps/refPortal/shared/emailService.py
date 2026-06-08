"""
Email Service for RefereeX
Handles sending emails with attachments using SMTP
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
import tempfile
import base64
from datetime import datetime
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger
from shared.messaging import MessagingService
from shared.reportsService import ReportsService

class EmailService:
    def __init__(self, logger: Logger, messagingService: MessagingService):
        self.logger = logger
        self.messagingService = messagingService
        
        # Initialize reports service for HTML generation
        self.reportsService = ReportsService(logger)
        
        # SMTP Configuration from environment variables
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.smtp_use_tls = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'
        
        # Email configuration
        self.from_email = os.getenv('FROM_EMAIL', 'noreply@refereex.com')
        self.from_name = os.getenv('FROM_NAME', 'RefereeX System')
        
        # Default recipients for reports
        self.default_report_recipients = [
            'openreports@refereex.com',
            'guyshachar.acc@gmail.com'
        ]
        
        self.logger.info(f'EmailService initialized with SMTP server: {self.smtp_server}:{self.smtp_port}')

    def send_email(
        self,
        to_emails: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        cc_emails: Optional[List[str]] = None,
        bcc_emails: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Send email with optional attachments
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            body_text: Plain text email body
            body_html: HTML email body (optional)
            attachments: List of attachment dictionaries with 'filename', 'content', 'mime_type'
            cc_emails: List of CC email addresses (optional)
            bcc_emails: List of BCC email addresses (optional)
            
        Returns:
            Dict with success status and message
        """
        try:
            if not self.smtp_username or not self.smtp_password:
                raise ValueError("SMTP credentials not configured")
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = ', '.join(to_emails)
            msg['Subject'] = subject
            
            if cc_emails:
                msg['Cc'] = ', '.join(cc_emails)
            
            # Add text body
            text_part = MIMEText(body_text, 'plain', 'utf-8')
            msg.attach(text_part)
            
            # Add HTML body if provided
            if body_html:
                html_part = MIMEText(body_html, 'html', 'utf-8')
                msg.attach(html_part)
            
            # Add attachments if provided
            if attachments:
                for attachment in attachments:
                    self._add_attachment(msg, attachment)
            
            # Convert to multipart/mixed if we have attachments
            if attachments:
                msg = self._convert_to_mixed(msg)
            
            # Send email
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls(context=context)
                server.login(self.smtp_username, self.smtp_password)
                
                # Prepare recipient list
                all_recipients = to_emails.copy()
                if cc_emails:
                    all_recipients.extend(cc_emails)
                if bcc_emails:
                    all_recipients.extend(bcc_emails)
                
                server.send_message(msg, to_addrs=all_recipients)
            
            self.logger.info(f'Email sent successfully to {len(to_emails)} recipients')
            return {
                'success': True,
                'message': f'Email sent successfully to {len(to_emails)} recipients',
                'recipients': to_emails
            }
            
        except Exception as e:
            self.logger.error(f'Failed to send email: {str(e)}')
            return {
                'success': False,
                'message': f'Failed to send email: {str(e)}',
                'error': str(e)
            }

    def send_report_email(
        self,
        report_data: Dict[str, Any],
        pdf_content: bytes,
        recipients: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Send game report email with PDF attachment
        
        Args:
            report_data: Dictionary containing report information
            pdf_content: PDF file content as bytes
            recipients: List of recipient emails (optional, uses default if not provided)
            
        Returns:
            Dict with success status and message
        """
        try:
            if recipients is None:
                recipients = self.default_report_recipients
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"open-game-report-{report_data.get('gameId', 'unknown')}-{timestamp}.pdf"
            
            # Create email content
            subject = f"דו״ח תיקון משחק - {report_data.get('gameTitle', 'משחק לא ידוע')}"
            
            # Text body
            body_text = self._create_report_text_body(report_data)
            
            # HTML body using ReportsService with HTTP URLs for email
            body_html = self.reportsService.generate_html_for_email(report_data)
            
            # Create attachment
            attachment = {
                'filename': filename,
                'content': pdf_content,
                'mime_type': 'application/pdf'
            }
            
            # Send email
            result = self.send_email_via_brevo(recipients, subject, body_text, body_html, attachment)
            
            return result
            
        except Exception as e:
            self.logger.error(f'Failed to send report email: {str(e)}')
            return {
                'success': False,
                'message': f'Failed to send report email: {str(e)}',
                'error': str(e)
            }

    def _add_attachment(self, msg: MIMEMultipart, attachment: Dict[str, Any]):
        """Add attachment to email message"""
        try:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment['content'])
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {attachment["filename"]}'
            )
            msg.attach(part)
        except Exception as e:
            self.logger.error(f'Failed to add attachment {attachment.get("filename", "unknown")}: {str(e)}')

    def _convert_to_mixed(self, msg: MIMEMultipart) -> MIMEMultipart:
        """Convert multipart/alternative to multipart/mixed for attachments"""
        mixed_msg = MIMEMultipart('mixed')
        mixed_msg['From'] = msg['From']
        mixed_msg['To'] = msg['To']
        mixed_msg['Subject'] = msg['Subject']
        if 'Cc' in msg:
            mixed_msg['Cc'] = msg['Cc']
        
        # Add the original message as a subpart
        mixed_msg.attach(msg)
        return mixed_msg

    def _create_report_text_body(self, report_data: Dict[str, Any]) -> str:
        """Create plain text email body for report"""
        return f"""
דו״ח תיקון משחק

פרטי המשחק:
- משחק: {report_data.get('gameTitle', 'לא ידוע')}
- תאריך: {report_data.get('gameDate', 'לא ידוע')}
- שעה: {report_data.get('gameTime', 'לא ידוע')}
- ליגה: {report_data.get('league', 'לא ידוע')}
- מגרש: {report_data.get('field', 'לא ידוע')}
- תפקיד: {report_data.get('role', 'לא ידוע')}

פרטי הדו״ח:
- תאריך יצירת הדו״ח: {report_data.get('reportDatetime', 'לא ידוע')}
- מדווח: {report_data.get('reporter', 'לא ידוע')}

קטגוריות שנבחרו:
{', '.join(report_data.get('categories', []))}

פרטים נוספים:
{report_data.get('details', 'אין פרטים נוספים')}

הדו״ח המלא מצורף כקובץ PDF.

בברכה,
מערכת RefereeX
        """.strip()

    def _create_report_html_body(self, report_data: Dict[str, Any]) -> str:
        """Create HTML email body for report"""
        categories_html = ''.join([f'<li>{cat}</li>' for cat in report_data.get('categories', [])])
        
        return f"""
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>דו״ח תיקון משחק</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            text-align: center;
            border-radius: 5px 5px 0 0;
        }}
        .content {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 0 0 5px 5px;
        }}
        .section {{
            margin-bottom: 20px;
        }}
        .section h3 {{
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }}
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        .info-table td {{
            padding: 8px;
            border-bottom: 1px solid #ddd;
        }}
        .info-table td:first-child {{
            font-weight: bold;
            width: 30%;
        }}
        .categories {{
            list-style-type: none;
            padding: 0;
        }}
        .categories li {{
            background-color: #e8f4f8;
            margin: 5px 0;
            padding: 10px;
            border-radius: 3px;
            border-right: 4px solid #3498db;
        }}
        .footer {{
            text-align: center;
            margin-top: 20px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>דו״ח תיקון משחק</h1>
    </div>
    
    <div class="content">
        <div class="section">
            <h3>פרטי המשחק</h3>
            <table class="info-table">
                <tr><td>משחק:</td><td>{report_data.get('gameTitle', 'לא ידוע')}</td></tr>
                <tr><td>תאריך:</td><td>{report_data.get('gameDate', 'לא ידוע')}</td></tr>
                <tr><td>שעה:</td><td>{report_data.get('gameTime', 'לא ידוע')}</td></tr>
                <tr><td>ליגה:</td><td>{report_data.get('league', 'לא ידוע')}</td></tr>
                <tr><td>מגרש:</td><td>{report_data.get('field', 'לא ידוע')}</td></tr>
                <tr><td>תפקיד:</td><td>{report_data.get('role', 'לא ידוע')}</td></tr>
            </table>
        </div>
        
        <div class="section">
            <h3>פרטי הדו״ח</h3>
            <table class="info-table">
                <tr><td>תאריך יצירת הדו״ח:</td><td>{report_data.get('reportDatetime', 'לא ידוע')}</td></tr>
                <tr><td>מדווח:</td><td>{report_data.get('reporter', 'לא ידוע')}</td></tr>
            </table>
        </div>
        
        <div class="section">
            <h3>קטגוריות שנבחרו</h3>
            <ul class="categories">
                {categories_html if categories_html else '<li>אין קטגוריות</li>'}
            </ul>
        </div>
        
        <div class="section">
            <h3>פרטים נוספים</h3>
            <p>{report_data.get('details', 'אין פרטים נוספים')}</p>
        </div>
    </div>
    
    <div class="footer">
        <p>הדו״ח המלא מצורף כקובץ PDF.</p>
        <p>בברכה,<br>מערכת RefereeX</p>
    </div>
</body>
</html>
        """.strip()

    def test_connection(self) -> Dict[str, Any]:
        """Test SMTP connection"""
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls(context=context)
                server.login(self.smtp_username, self.smtp_password)
            
            return {
                'success': True,
                'message': 'SMTP connection successful'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'SMTP connection failed: {str(e)}',
                'error': str(e)
            }
