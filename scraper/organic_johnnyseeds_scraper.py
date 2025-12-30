#!/usr/bin/env python3
"""
Johnny's Seeds organic seed scraper for USDA NOP recordkeeping.

Scrapes only certified organic seeds from johnnyseeds.com with
enhanced treatment detection and organic certification tracking.
"""

import os
import json
import time
import re
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from organic_seed_scraper import OrganicSeedScraper
from seed_name_parser import parse_with_botanical_field_names
from scraper_utils import (
    parse_weight_from_string, standardize_size_format, extract_price,
    clean_text, make_absolute_url
)


class JohnnySeedsOrganicScraper(OrganicSeedScraper):
    """
    Organic seed scraper for Johnny's Selected Seeds.

    Filters to only organic products and captures treatment information
    for USDA NOP recordkeeping.
    """

    # Supplier configuration
    SUPPLIER_NAME = "Johnny's Selected Seeds"
    SUPPLIER_WEBSITE = "https://johnnyseeds.com"
    CURRENCY_CODE = "USD"

    # Organic category URLs - use Johnny's organic filter
    ORGANIC_CATEGORY_URLS = [
        # Microgreens - organic only
        "https://johnnyseeds.com/vegetables/microgreens/?prefn1=Organic&prefv1=true",
        # Vegetables - organic only
        "https://johnnyseeds.com/vegetables/tomatoes/?prefn1=Organic&prefv1=true",
        # Could add more categories:
        # "https://johnnyseeds.com/vegetables/?prefn1=Organic&prefv1=true",
        # "https://johnnyseeds.com/herbs/?prefn1=Organic&prefv1=true",
    ]

    def __init__(
        self,
        categories: List[str] = None,
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 3
    ):
        """
        Initialize Johnny's organic scraper.

        Args:
            categories: List of category URLs to scrape (defaults to microgreens)
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
            self.category_urls = self.ORGANIC_CATEGORY_URLS

    def get_start_urls(self) -> List[str]:
        """Get organic-filtered category URLs."""
        return self.category_urls

    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract organic product links from category page.

        Args:
            page_url: URL of the category page

        Returns:
            List of product dictionaries
        """
        self.logger.info(f"Extracting product links from: {page_url}")
        products = []

        # Extract category from URL (e.g., /vegetables/tomatoes/ -> Tomatoes)
        category = None
        # Parse URL path to get the last segment before query params
        url_path = page_url.split('?')[0].rstrip('/')
        path_parts = url_path.split('/')
        if path_parts:
            category = path_parts[-1].replace('-', ' ').title()

        try:
            # Navigate to page
            if self.page.url != page_url:
                self.page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
                self._handle_popups()

            # Wait for products to load
            try:
                self.page.wait_for_selector('.product-tile', timeout=10000)
            except PlaywrightTimeoutError:
                self.logger.warning("Product tiles not found")
                return products

            # Load all products (handle "View More" pagination)
            self._load_all_products()

            # Extract product tiles
            tiles = self.page.locator('.product-tile').all()
            self.logger.info(f"Found {len(tiles)} product tiles")

            for tile in tiles:
                try:
                    product = self._extract_product_from_tile(tile, category=category)
                    if product:
                        products.append(product)
                except Exception as e:
                    self.logger.debug(f"Error extracting tile: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error extracting products: {e}")

        self.logger.info(f"Extracted {len(products)} products")
        return products

    def _extract_product_from_tile(self, tile, category: str = None) -> Optional[Dict[str, Any]]:
        """Extract product info from a single tile element."""
        # Get URL
        link = tile.locator('a.tile-name-link').first
        if link.count() == 0:
            return None

        href = link.get_attribute('href')
        if not href:
            return None

        url = make_absolute_url(href, self.SUPPLIER_WEBSITE)

        # Get title
        title_elem = tile.locator('.tile-name.product-name').first
        if title_elem.count() == 0:
            return None

        title = clean_text(title_elem.text_content())
        if not title:
            return None

        # Try to extract more specific category from product URL
        # e.g., /flowers/zinnias/benarys-giant-series/ -> Zinnias
        product_category = category
        url_parts = url.split('/')
        if len(url_parts) >= 5:
            # URL format: domain/category/subcategory/series/product
            # Look for common plant categories in URL path
            for part in url_parts[3:6]:  # Check a few path segments
                normalized = part.replace('-', ' ').title()
                if normalized and normalized != product_category:
                    # Check if this looks like a plant category
                    from seed_naming_utils import COMMON_NAME_MAPPING
                    if part.lower().rstrip('s') in COMMON_NAME_MAPPING or part.lower() in COMMON_NAME_MAPPING:
                        product_category = normalized
                        break

        # Parse botanical name with category hint
        parsed = parse_with_botanical_field_names(title, category=product_category)

        # Since we're using organic-filtered URLs (?prefn1=Organic&prefv1=true),
        # all products from this page ARE certified organic by Johnny's filter.
        # Pre-set organic status to avoid false negatives from keyword detection.
        return {
            'title': title,
            'url': url,
            'common_name': parsed.get('common_name', 'Unknown'),
            'cultivar_name': parsed.get('cultivar_name', 'N/A'),
            'category': product_category,
            'organic_status': {
                'is_certified_organic': True,
                'certification_type': 'USDA Organic',
                'confidence': 'high',
                'indicators_found': ['johnny_organic_filter'],
                'non_gmo_verified': False  # Will be updated if detected
            }
        }

    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed product information including treatment.

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

        try:
            # Navigate to product page
            self.page.goto(product['url'], timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            # Extract description and details for treatment detection
            description = self._get_product_description()
            product_details = self._get_product_details_section()

            # Detect seed treatment
            detailed['seed_treatment'] = self._extract_treatment_info(
                title=product['title'],
                description=description,
                product_details=product_details
            )

            # Extract lot info if available
            detailed['lot_info'] = self._extract_lot_info(product_details)

            # Extract variations (sizes/prices)
            detailed['variations'] = self._extract_variations(product)
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
                '.pdp-description',
                '.description-content',
                '[data-component="ProductDescription"]'
            ]

            for selector in selectors:
                elem = self.page.locator(selector).first
                if elem.count() > 0:
                    text = elem.text_content()
                    if text:
                        return clean_text(text)

        except Exception as e:
            self.logger.debug(f"Error getting description: {e}")

        return ""

    def _get_product_details_section(self) -> Dict[str, str]:
        """Extract product details/specs section."""
        details = {}

        try:
            # Look for details table or list
            detail_rows = self.page.locator('.product-details dt, .product-details dd').all()

            if len(detail_rows) >= 2:
                for i in range(0, len(detail_rows) - 1, 2):
                    key = clean_text(detail_rows[i].text_content())
                    value = clean_text(detail_rows[i + 1].text_content())
                    if key and value:
                        details[key.lower()] = value

            # Also check for quick facts
            quick_facts = self.page.locator('.quick-facts li').all()
            for fact in quick_facts:
                text = clean_text(fact.text_content())
                if ':' in text:
                    key, value = text.split(':', 1)
                    details[key.lower().strip()] = value.strip()

        except Exception as e:
            self.logger.debug(f"Error getting details: {e}")

        return details

    def _extract_lot_info(self, product_details: Dict[str, str]) -> Dict[str, Any]:
        """Extract lot number and germination info if available."""
        lot_info = {
            'lot_number': None,
            'germination_rate': None,
            'test_date': None
        }

        # Check product details for germination rate
        for key, value in product_details.items():
            if 'germination' in key.lower():
                lot_info['germination_rate'] = value
            elif 'lot' in key.lower():
                lot_info['lot_number'] = value
            elif 'test' in key.lower() and 'date' in key.lower():
                lot_info['test_date'] = value

        return lot_info

    def _extract_variations(self, product: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract size/price variations from product page.

        Uses API calls to Johnny's for accurate pricing.
        """
        variations = []

        try:
            # Extract base SKU from URL
            url_path = self.page.url
            base_sku_match = re.search(r'-([0-9A-Z]+)\.html', url_path)
            if not base_sku_match:
                base_sku_match = re.search(r'([0-9]+[A-Z]*)', url_path)

            if not base_sku_match:
                self.logger.warning(f"Could not extract SKU from URL: {url_path}")
                return variations

            base_sku = base_sku_match.group(1)
            self.logger.debug(f"Base SKU: {base_sku}")

            # Johnny's uses SKU suffixes for sizes
            size_suffixes = [
                ('26', '1 Ounce'),
                ('30', '1/4 Pound'),
                ('32', '1 Pound'),
                ('36', '5 Pounds'),
                ('38', '25 Pounds')
            ]

            for suffix, default_size in size_suffixes:
                variation = self._fetch_variation(base_sku, suffix, default_size)
                if variation:
                    variations.append(variation)

        except Exception as e:
            self.logger.error(f"Error extracting variations: {e}")

        return variations

    def _fetch_variation(
        self,
        base_sku: str,
        suffix: str,
        default_size: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single variation from Johnny's API."""
        try:
            sku = f"{base_sku}.{suffix}"
            api_url = (
                f"https://johnnyseeds.com/on/demandware.store/"
                f"Sites-JSS-Site/en_US/Product-Variation?pid={sku}&quantity=1"
            )

            response = self.page.goto(api_url, timeout=10000, wait_until="domcontentloaded")

            if response and response.status == 200:
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    json_text = self.page.locator('body').text_content()
                    data = json.loads(json_text)

                    product_data = data.get('product', {})
                    if product_data:
                        # Extract price
                        price_info = product_data.get('price', {})
                        price = 0.0
                        if isinstance(price_info, dict):
                            if 'sales' in price_info:
                                sales = price_info['sales']
                                price = float(sales.get('value', 0) if isinstance(sales, dict) else sales or 0)
                            elif 'list' in price_info:
                                list_p = price_info['list']
                                price = float(list_p.get('value', 0) if isinstance(list_p, dict) else list_p or 0)

                        if price <= 0:
                            return None

                        # Extract actual size from variation attributes
                        actual_size = default_size
                        for attr in product_data.get('variationAttributes', []):
                            if attr.get('attributeId') == 'sizecode':
                                for value in attr.get('values', []):
                                    if value.get('pid') == sku:
                                        actual_size = value.get('displayValue', default_size)
                                        break

                        # Parse weight
                        weight_kg, orig_value, orig_unit = parse_weight_from_string(actual_size)

                        return {
                            'size': standardize_size_format(actual_size),
                            'price': price,
                            'is_variation_in_stock': product_data.get('available', False),
                            'weight_kg': weight_kg,
                            'original_weight_value': orig_value,
                            'original_weight_unit': orig_unit,
                            'sku': product_data.get('id', sku)
                        }

        except json.JSONDecodeError:
            self.logger.debug(f"Not JSON for SKU {base_sku}.{suffix}")
        except Exception as e:
            self.logger.debug(f"Error fetching variation: {e}")

        return None

    def _handle_popups(self) -> None:
        """Handle cookie consent and email popups."""
        try:
            # Cookie consent
            consent_selectors = [
                '#onetrust-accept-btn-handler',
                'button:has-text("Accept All")',
                '.onetrust-accept-btn'
            ]

            for selector in consent_selectors:
                btn = self.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    break

            # Email modal
            modal_selectors = [
                '.ltkmodal-close',
                '.modal-close',
                '[aria-label="Close"]'
            ]

            for selector in modal_selectors:
                btn = self.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break

        except Exception as e:
            self.logger.debug(f"Popup handling: {e}")

    def _load_all_products(self) -> None:
        """Load all products using 'View More' pagination."""
        max_attempts = 10
        attempt = 0

        while attempt < max_attempts:
            current_count = self.page.locator('.product-tile').count()
            self.logger.debug(f"Current product count: {current_count}")

            # Look for View More link
            view_more = self.page.locator('a.btn.more').first

            if view_more.count() > 0 and view_more.is_visible():
                try:
                    self._handle_popups()
                    view_more.click()
                    time.sleep(3)

                    new_count = self.page.locator('.product-tile').count()
                    if new_count > current_count:
                        self.logger.info(f"Loaded more: {current_count} -> {new_count}")
                        attempt += 1
                        continue
                    else:
                        break
                except Exception as e:
                    self.logger.debug(f"View More click error: {e}")
                    break
            else:
                break

            attempt += 1

        final_count = self.page.locator('.product-tile').count()
        self.logger.info(f"Final product count: {final_count}")

    def get_politeness_delay(self) -> float:
        """Delay between requests."""
        return 1.5


def main():
    """Run the Johnny's Seeds organic scraper."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape organic seeds from Johnny's Selected Seeds"
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

    scraper = JohnnySeedsOrganicScraper(
        test_mode=args.test,
        test_limit=args.limit,
        headless=not args.no_headless
    )
    scraper.run()


if __name__ == "__main__":
    main()
