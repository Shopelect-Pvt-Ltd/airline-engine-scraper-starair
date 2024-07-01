import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pdfkit
import re
import os
from utils import s3

def fetch_invoices(gstin, book_code, airline):
    # Login session
    session = requests.Session()
    # Load the login page
    login_url = 'https://starair.in/customer/gstinvoice'
    response = session.get(login_url)
    soup = BeautifulSoup(response.content, 'html.parser')
    # Fill in the login credentials and submit
    form = soup.find('form', id='form1')
    if form:
        token = form.find('input', {'name': '__RequestVerificationToken'})['value']
        payload = {
            'Book_code': book_code,
            'CustGSTIN': gstin,
            '__RequestVerificationToken': token,
            'action': 'Search'
        }
        response = session.post(login_url, data=payload)
        # Check if login is successful and proceed to scrape invoices
        if response.url == login_url:
            logging.info(f"Login successful for GSTIN: {gstin} and Book_code: {book_code}")
            # Extract invoices links from the page
            soup = BeautifulSoup(response.content, 'html.parser')
            download_links = soup.find_all('a', href=True, string='Print')
            links = list(download_links)
            if not links:
                logging.info("No invoice download links found.")
                return False,[]
            else:
                pdf_s3links=[]
                for i, link in enumerate(links, 1):
                    html = str(link)
                    pattern = r'href="([^"]*)"'
                    match = re.search(pattern, html)
                    if match:
                        href_value = match.group(1)  # Get the URL from the href attribute
                        base_url = 'https://starair.in/customer'
                        invoice_response = session.get(urljoin(base_url, href_value))
                        html_content = invoice_response.content.decode('utf-8')

                        if html_content.strip():
                            pdf_filename = f"{gstin}_{book_code}_invoice_{i}.pdf"
                            try:
                                pdfkit.from_string(html_content,'temp/'+pdf_filename,options={"enable-local-file-access": ""})
                                logging.info(f"Invoice {i}: PDF saved successfully at {pdf_filename}")
                                filepath = os.path.join(os.getcwd(), "temp") + "/" + pdf_filename
                                pdf_status, pdf_s3link = s3.upload_s3(filepath, pdf_filename, airline)
                                logging.info("File Uploaded to S3")
                                if os.path.exists(filepath):
                                    os.remove(filepath)
                                    logging.info(f"{filepath} has been deleted.")
                                else:
                                    logging.info(f"{filepath} does not exist.")
                                pdf_s3links.append(pdf_s3link)
                            except Exception as e:
                                logging.info(f"Error converting Invoice {i} to PDF: {str(e)}")
                                return False,[]
                    return True,pdf_s3links
                logging.info(f"Total {len(links)} invoices downloaded.")
        else:
            logging.info(f"Login failed for GSTIN: {gstin} and Book_code: {book_code}")
            return False,[]
    else:
        logging.info("Login form not found.")
        return False,[]


def startair_scraper(data):
    max_attempts = 3
    try:
        vendor = data['Vendor']
        airline = 'starair'
        if vendor == 'Star Air':
            airline = 'starair'
        book_code = data['Ticket/PNR']
        gstin=data['Customer_GSTIN']
        success = False
        for attempt in range(max_attempts):
            status, pdf_s3links = fetch_invoices(gstin, book_code, airline)
            if status:
                return {
                    "success": True,
                    "message": "FILE_PUSHED_TO_S3",
                    "data": {'s3_link': pdf_s3links, 'airline': airline}
                }
            else:
                logging.info(f"Attempt {attempt + 1} failed for Booking Code: {book_code}. Retrying...")

        if not success:
            logging.info(f"Failed to download files after {max_attempts} attempts for Booking Code: {book_code}")
            return {
                "success": False,
                "message": "ERROR_PROCESSING",
                "data": {}
            }
    except Exception as e:
        logging.info("Error in starair_scraper function:", e)
        return {
            "success": False,
            "message": "ERROR_PROCESSING",
            "data": {}
        }
    