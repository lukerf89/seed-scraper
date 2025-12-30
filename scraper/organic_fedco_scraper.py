#!/usr/bin/env python3
"""
Fedco Seeds organic seed scraper for USDA NOP recordkeeping.

Scrapes certified organic seeds from Fedco's organic listing page
with treatment detection and pricing extraction.
"""

import os
import json
import time
import re
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from organic_seed_scraper import OrganicSeedScraper
from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    parse_weight_from_string, standardize_size_format, extract_price,
    clean_text, make_absolute_url
)


class FedcoOrganicScraper(OrganicSeedScraper):
    """
    Organic seed scraper for Fedco Seeds.

    Uses Fedco's organic filter at /seeds/list-organic to scrape
    only certified organic products.
    """

    # Supplier configuration
    SUPPLIER_NAME = "Fedco Seeds"
    SUPPLIER_WEBSITE = "https://www.fedcoseeds.com"
    CURRENCY_CODE = "USD"

    # Organic listing URL
    ORGANIC_LIST_URL = "https://www.fedcoseeds.com/seeds/list-organic"

    # Items per page (Fedco default)
    ITEMS_PER_PAGE = 50

    def __init__(
        self,
        categories: List[str] = None,
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 3
    ):
        """
        Initialize Fedco organic scraper.

        Args:
            categories: Optional list of category URLs (defaults to organic list)
            headless: Run browser in headless mode
            test_mode: Limit scraping for testing
            test_limit: Number of products in test mode
        """
        super().__init__(
            headless=headless,
            test_mode=test_mode,
            test_limit=test_limit
        )

        # Allow custom category URLs
        if categories:
            self.category_urls = categories
        else:
            self.category_urls = [self.ORGANIC_LIST_URL]

    def get_start_urls(self) -> List[str]:
        """Get organic listing URLs."""
        return self.category_urls

    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract organic product links from listing page with pagination.

        Args:
            page_url: URL of the listing page

        Returns:
            List of product dictionaries
        """
        self.logger.info(f"Extracting product links from: {page_url}")
        products = []
        current_url = page_url
        page_num = 1

        while True:
            try:
                # Navigate to page
                self.page.goto(current_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)

                # Wait for products to load
                try:
                    self.page.wait_for_selector('.search-result-item', timeout=10000)
                except PlaywrightTimeoutError:
                    self.logger.warning(f"No products found on page {page_num}")
                    break

                # Extract product items from current page
                items = self.page.locator('.search-result-item').all()
                self.logger.info(f"Page {page_num}: Found {len(items)} products")

                for item in items:
                    try:
                        product = self._extract_product_from_item(item)
                        if product:
                            products.append(product)
                    except Exception as e:
                        self.logger.debug(f"Error extracting item: {e}")
                        continue

                # Check for next page
                next_page = self._get_next_page_url(page_num)
                if next_page and not self.test_mode:
                    current_url = next_page
                    page_num += 1
                    time.sleep(self.get_politeness_delay())
                else:
                    break

            except Exception as e:
                self.logger.error(f"Error on page {page_num}: {e}")
                break

        self.logger.info(f"Extracted {len(products)} total products")
        return products

    def _get_next_page_url(self, current_page: int) -> Optional[str]:
        """Get URL for next pagination page."""
        try:
            # Look for next page link
            next_link = self.page.locator(f'a[href*="page={current_page + 1}"]').first
            if next_link.count() > 0:
                href = next_link.get_attribute('href')
                if href:
                    return make_absolute_url(href, self.SUPPLIER_WEBSITE)

            # Alternative: check if there are more pages
            pagination = self.page.locator('.pagination a, [class*="page"]').all()
            for link in pagination:
                text = link.text_content() or ''
                if text.strip() == str(current_page + 1):
                    href = link.get_attribute('href')
                    if href:
                        return make_absolute_url(href, self.SUPPLIER_WEBSITE)

        except Exception as e:
            self.logger.debug(f"No next page: {e}")
        return None

    def _extract_product_from_item(self, item) -> Optional[Dict[str, Any]]:
        """Extract product info from a search result item."""
        try:
            # Get data from data-item attribute (contains JSON)
            item_data_str = item.get_attribute('data-item')
            if item_data_str:
                item_data = json.loads(item_data_str)
            else:
                item_data = {}

            # Get item number
            item_number = item.get_attribute('data-item-number')
            if not item_number:
                item_number = item_data.get('number')

            if not item_number:
                return None

            # Get abbreviated name
            abbrev_name = item.get_attribute('data-item-abbreviatedname')
            if not abbrev_name:
                abbrev_name = item_data.get('abbreviatedName', '')

            # Get category
            category = item.get_attribute('data-item-category')
            if not category:
                category = item_data.get('category', '')

            # Get product URL from link
            link = item.locator('a[href*="/seeds/"]').first
            if link.count() == 0:
                return None

            href = link.get_attribute('href')
            if not href or 'list-' in href:
                # Skip filter links
                link = item.locator('.search-results-primary-info a').first
                if link.count() > 0:
                    href = link.get_attribute('href')

            if not href:
                return None

            url = make_absolute_url(href, self.SUPPLIER_WEBSITE)

            # Get full title from link text
            title_text = ''
            title_link = item.locator('.search-results-primary-info a').first
            if title_link.count() > 0:
                title_text = clean_text(title_link.text_content())

            if not title_text:
                title_text = abbrev_name

            # Parse botanical name with category hint
            parsed = parse_with_botanical_field_names(title_text, category=category)

            # Check for organic badge (should always be present on /list-organic)
            has_organic_badge = item.locator('.og-eco-overlay-badge img[src*="organic"]').count() > 0

            # Get days to maturity if available
            days_to_maturity = None
            # This might be in the description text

            return {
                'title': title_text,
                'url': url,
                'sku': str(item_number),
                'common_name': parsed.get('common_name', 'Unknown'),
                'cultivar_name': parsed.get('cultivar_name', 'N/A'),
                'category': category,
                'organic_status': {
                    'is_certified_organic': True,
                    'certification_type': 'Certified Organic',
                    'confidence': 'high',
                    'indicators_found': ['fedco_organic_filter', 'organic_badge'] if has_organic_badge else ['fedco_organic_filter'],
                    'non_gmo_verified': False
                }
            }

        except Exception as e:
            self.logger.debug(f"Error parsing item: {e}")
            return None

    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed product information including pricing.

        Args:
            product: Basic product info

        Returns:
            Complete product dictionary with organic fields
        """
        self.logger.info(f"Scraping details for: {product['title']}")

        # Get base details from parent
        detailed = super().scrape_product_details(product)

        # Initialize fields
        detailed['is_in_stock'] = False
        detailed['variations'] = []
        detailed['seed_treatment'] = {
            'has_treatment': False,
            'treatment_type': 'Unknown',
            'treatment_details': None,
            'is_organic_approved': True,
            'detection_confidence': 'unknown',
            'info_source': 'not_found'
        }
        detailed['lot_info'] = {
            'lot_number': None,
            'germination_rate': None,
            'test_date': None
        }
        detailed['days_to_maturity'] = None
        detailed['plant_type'] = None

        try:
            # Navigate to product page
            self.page.goto(product['url'], timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            # Extract description
            description = self._get_product_description()
            product_details = self._get_product_details_section()

            # Detect seed treatment
            detailed['seed_treatment'] = self._extract_treatment_info(
                title=product['title'],
                description=description,
                product_details=product_details
            )

            # Extract days to maturity
            detailed['days_to_maturity'] = self._extract_days_to_maturity(description)

            # Extract plant type
            detailed['plant_type'] = self._extract_plant_type(description)

            # Extract germination rate from Fedco's lookup
            detailed['lot_info'] = self._extract_lot_info(product_details)

            # Extract variations (sizes/prices) from radio buttons
            detailed['variations'] = self._extract_variations()
            detailed['is_in_stock'] = any(
                v.get('is_variation_in_stock', False)
                for v in detailed['variations']
            )

        except Exception as e:
            self.logger.error(f"Error scraping details: {e}")

        return detailed

    def _get_product_description(self) -> str:
        """Get product description from page."""
        try:
            selectors = [
                '.product-description',
                '.item-description',
                '.description',
                'article p',
                '.main-content p'
            ]

            texts = []
            for selector in selectors:
                elems = self.page.locator(selector).all()
                for elem in elems[:3]:  # Get first few paragraphs
                    text = elem.text_content()
                    if text and len(text.strip()) > 20:
                        texts.append(clean_text(text))

            return ' '.join(texts)

        except Exception as e:
            self.logger.debug(f"Error getting description: {e}")

        return ""

    def _get_product_details_section(self) -> Dict[str, str]:
        """Extract product details/specs section."""
        details = {}

        try:
            # Look for the comparison table
            table = self.page.locator('table.comparison-chart').first
            if table.count() > 0:
                rows = table.locator('tr').all()
                if len(rows) >= 2:
                    # First row is headers
                    headers = rows[0].locator('th').all()
                    header_texts = [clean_text(h.text_content()).lower() for h in headers]

                    # Find the row for this product (highlighted)
                    for row in rows[1:]:
                        if 'bg-' in (row.get_attribute('class') or ''):
                            cells = row.locator('td').all()
                            for i, cell in enumerate(cells):
                                if i < len(header_texts):
                                    details[header_texts[i]] = clean_text(cell.text_content())
                            break

        except Exception as e:
            self.logger.debug(f"Error getting details: {e}")

        return details

    def _extract_days_to_maturity(self, description: str) -> Optional[str]:
        """Extract days to maturity from description or table."""
        patterns = [
            r'(\d+)\s*(?:to\s*\d+)?\s*days?\s*(?:to\s*)?(?:maturity|harvest)',
            r'days?\s*to\s*maturity[:\s]*(\d+)',
            r'matures?\s*in\s*(\d+)\s*days?',
            r'(\d+)\s*days'
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1) + " days"
        return None

    def _extract_plant_type(self, description: str) -> Optional[str]:
        """Extract plant type (open-pollinated, hybrid, etc.)."""
        types = []

        if re.search(r'\bopen[- ]pollinated\b|\bOP\b', description, re.IGNORECASE):
            types.append('Open-Pollinated')
        elif re.search(r'\bhybrid\b|\bF1\b', description, re.IGNORECASE):
            types.append('Hybrid')

        if re.search(r'\bheirloom\b', description, re.IGNORECASE):
            types.append('Heirloom')

        if re.search(r'\bindeterminate\b', description, re.IGNORECASE):
            types.append('Indeterminate')
        elif re.search(r'\bdeterminate\b', description, re.IGNORECASE):
            types.append('Determinate')

        return ', '.join(types) if types else None

    def _extract_lot_info(self, product_details: Dict[str, str]) -> Dict[str, Any]:
        """Extract lot and germination info."""
        lot_info = {
            'lot_number': None,
            'germination_rate': None,
            'test_date': None
        }

        # Fedco has a germination lookup tool - we'd need to check that separately
        # For now, return empty

        return lot_info

    def _extract_variations(self) -> List[Dict[str, Any]]:
        """
        Extract size/price variations from product page.

        Fedco uses radio buttons with data-fedco-itemsize JSON attribute.
        """
        variations = []

        try:
            # Find all size radio buttons
            radios = self.page.locator('input[type="radio"][data-fedco-itemsize]').all()

            for radio in radios:
                size_data_str = radio.get_attribute('data-fedco-itemsize')
                if not size_data_str:
                    continue

                try:
                    size_data = json.loads(size_data_str)

                    display_amount = size_data.get('display_amount', '')
                    price_str = size_data.get('price', '0')
                    in_stock = size_data.get('in_stock', True)

                    # Handle price (may be string or int in cents)
                    if isinstance(price_str, str):
                        price = float(price_str)
                    else:
                        price = float(price_str) / 100  # Convert cents to dollars

                    # Parse weight
                    weight_kg, orig_value, orig_unit = parse_weight_from_string(display_amount)

                    # Get size code (A, B, C, etc.)
                    size_code = radio.get_attribute('value') or ''

                    variations.append({
                        'size': standardize_size_format(display_amount),
                        'size_code': size_code,
                        'price': price,
                        'is_variation_in_stock': bool(in_stock),
                        'weight_kg': weight_kg,
                        'original_weight_value': orig_value,
                        'original_weight_unit': orig_unit,
                        'sku': None  # SKU is the item number + size code
                    })

                except json.JSONDecodeError:
                    self.logger.debug(f"Could not parse size data: {size_data_str[:50]}")
                    continue

        except Exception as e:
            self.logger.debug(f"Error extracting variations: {e}")

        return variations

    def get_politeness_delay(self) -> float:
        """Delay between requests."""
        return 2.0  # Be polite to Fedco's servers


def main():
    """Run the Fedco organic scraper."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape organic seeds from Fedco Seeds"
    )
    parser.add_argument(
        '--test', action='store_true',
        help='Run in test mode (limited products)'
    )
    parser.add_argument(
        '--limit', type=int, default=3,
        help='Number of products to test (default: 3)'
    )
    parser.add_argument(
        '--no-headless', action='store_true',
        help='Show browser window'
    )

    args = parser.parse_args()

    scraper = FedcoOrganicScraper(
        test_mode=args.test,
        test_limit=args.limit,
        headless=not args.no_headless
    )
    scraper.run()


if __name__ == "__main__":
    main()
