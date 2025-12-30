#!/usr/bin/env python3
"""
High Mowing Organic Seeds scraper for USDA NOP recordkeeping.

High Mowing is 100% certified organic, so all products are organic by default.
This scraper captures treatment info and product variations for organic recordkeeping.
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


class HighMowingOrganicScraper(OrganicSeedScraper):
    """
    Organic seed scraper for High Mowing Organic Seeds.

    High Mowing is 100% certified organic - all products are organic
    by definition, so no filtering is needed.
    """

    # Supplier configuration
    SUPPLIER_NAME = "High Mowing Organic Seeds"
    SUPPLIER_WEBSITE = "https://www.highmowingseeds.com"
    CURRENCY_CODE = "USD"

    # Category URLs to scrape
    CATEGORY_URLS = [
        # Vegetables
        "https://www.highmowingseeds.com/vegetables/tomatoes.html",
        # Can add more categories:
        # "https://www.highmowingseeds.com/vegetables/peppers.html",
        # "https://www.highmowingseeds.com/vegetables/lettuce-salad-greens.html",
        # "https://www.highmowingseeds.com/herbs.html",
    ]

    # Items per page for pagination
    ITEMS_PER_PAGE = 25

    def __init__(
        self,
        categories: List[str] = None,
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 3
    ):
        """
        Initialize High Mowing organic scraper.

        Args:
            categories: List of category URLs to scrape
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
            self.category_urls = self.CATEGORY_URLS

    def get_start_urls(self) -> List[str]:
        """Get category URLs with pagination parameter."""
        # Add items-per-page parameter for efficiency
        urls = []
        for url in self.category_urls:
            if '?' in url:
                urls.append(f"{url}&product_list_limit={self.ITEMS_PER_PAGE}")
            else:
                urls.append(f"{url}?product_list_limit={self.ITEMS_PER_PAGE}")
        return urls

    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract product links from category page with pagination.

        Args:
            page_url: URL of the category page

        Returns:
            List of product dictionaries
        """
        self.logger.info(f"Extracting product links from: {page_url}")
        products = []
        current_url = page_url
        page_num = 1

        # Extract category from URL (e.g., /vegetables/tomatoes.html -> Tomatoes)
        category = None
        category_match = re.search(r'/([^/]+)\.html', page_url)
        if category_match:
            category = category_match.group(1).replace('-', ' ').title()

        while True:
            try:
                # Navigate to page
                self.page.goto(current_url, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)
                self._handle_popups()

                # Wait for products to load
                try:
                    self.page.wait_for_selector('.product-item', timeout=10000)
                except PlaywrightTimeoutError:
                    self.logger.warning(f"No product items found on page {page_num}")
                    break

                # Extract product tiles from current page
                tiles = self.page.locator('.product-item').all()
                self.logger.info(f"Page {page_num}: Found {len(tiles)} products")

                for tile in tiles:
                    try:
                        product = self._extract_product_from_tile(tile, category=category)
                        if product:
                            products.append(product)
                    except Exception as e:
                        self.logger.debug(f"Error extracting tile: {e}")
                        continue

                # Check for next page
                next_page = self._get_next_page_url()
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

    def _get_next_page_url(self) -> Optional[str]:
        """Get URL for next pagination page."""
        try:
            # Look for next page link
            next_link = self.page.locator('a.action.next').first
            if next_link.count() > 0:
                href = next_link.get_attribute('href')
                if href:
                    return make_absolute_url(href, self.SUPPLIER_WEBSITE)
        except Exception as e:
            self.logger.debug(f"No next page: {e}")
        return None

    def _extract_product_from_tile(self, tile, category: str = None) -> Optional[Dict[str, Any]]:
        """Extract product info from a single tile element."""
        # Get product link
        link = tile.locator('a.product-item-link').first
        if link.count() == 0:
            # Try alternate selector
            link = tile.locator('.product-item-name a').first
            if link.count() == 0:
                return None

        href = link.get_attribute('href')
        if not href:
            return None

        url = make_absolute_url(href, self.SUPPLIER_WEBSITE)

        # Get title
        title = clean_text(link.text_content())
        if not title:
            return None

        # Parse botanical name with category hint
        parsed = parse_with_botanical_field_names(title, category=category)

        # High Mowing is 100% certified organic - all products are organic
        return {
            'title': title,
            'url': url,
            'common_name': parsed.get('common_name', 'Unknown'),
            'cultivar_name': parsed.get('cultivar_name', 'N/A'),
            'category': category,
            'organic_status': {
                'is_certified_organic': True,
                'certification_type': 'USDA Organic',
                'confidence': 'high',
                'indicators_found': ['high_mowing_100_percent_organic'],
                'non_gmo_verified': True  # High Mowing is Non-GMO Project Verified
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
        detailed['days_to_maturity'] = None
        detailed['plant_type'] = None

        try:
            # Navigate to product page
            self.page.goto(product['url'], timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            # Extract SKU
            detailed['sku'] = self._extract_sku()

            # Extract description and details
            description = self._get_product_description()
            product_details = self._get_product_details_section()

            # Detect seed treatment
            detailed['seed_treatment'] = self._extract_treatment_info(
                title=product['title'],
                description=description,
                product_details=product_details
            )

            # Extract additional product attributes
            detailed['days_to_maturity'] = self._extract_days_to_maturity(description)
            detailed['plant_type'] = self._extract_plant_type(description)

            # Extract variations from JSON config
            detailed['variations'] = self._extract_variations()
            detailed['is_in_stock'] = any(
                v.get('is_variation_in_stock', False)
                for v in detailed['variations']
            )

        except Exception as e:
            self.logger.error(f"Error scraping details: {e}")

        return detailed

    def _extract_sku(self) -> Optional[str]:
        """Extract base SKU from product page."""
        try:
            sku_elem = self.page.locator('.product.attribute.sku .value').first
            if sku_elem.count() > 0:
                return clean_text(sku_elem.text_content())
        except Exception as e:
            self.logger.debug(f"Error extracting SKU: {e}")
        return None

    def _get_product_description(self) -> str:
        """Get product description from page."""
        try:
            selectors = [
                '.product.attribute.description .value',
                '.product-info-main .value',
                '.product.info.detailed',
                '#description'
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
            # Look for attribute list items
            attr_rows = self.page.locator('.product-info-main li').all()

            for row in attr_rows:
                text = clean_text(row.text_content())
                if ':' in text:
                    key, value = text.split(':', 1)
                    details[key.lower().strip()] = value.strip()

            # Also check for additional attributes table
            table_rows = self.page.locator('.additional-attributes tr').all()
            for row in table_rows:
                cells = row.locator('th, td').all()
                if len(cells) >= 2:
                    key = clean_text(cells[0].text_content())
                    value = clean_text(cells[1].text_content())
                    if key and value:
                        details[key.lower()] = value

        except Exception as e:
            self.logger.debug(f"Error getting details: {e}")

        return details

    def _extract_days_to_maturity(self, description: str) -> Optional[str]:
        """Extract days to maturity from description."""
        patterns = [
            r'(\d+)\s*(?:to\s*\d+)?\s*days?\s*(?:to\s*)?(?:maturity|harvest)',
            r'days?\s*to\s*maturity[:\s]*(\d+)',
            r'matures?\s*in\s*(\d+)\s*days?',
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1) + " days"
        return None

    def _extract_plant_type(self, description: str) -> Optional[str]:
        """Extract plant type (determinate/indeterminate, etc.)."""
        types = []

        if re.search(r'\bindeterminate\b', description, re.IGNORECASE):
            types.append('Indeterminate')
        elif re.search(r'\bdeterminate\b', description, re.IGNORECASE):
            types.append('Determinate')

        if re.search(r'\bopen[- ]pollinated\b', description, re.IGNORECASE):
            types.append('Open-Pollinated')
        elif re.search(r'\bhybrid\b|\bF1\b', description, re.IGNORECASE):
            types.append('Hybrid')

        if re.search(r'\bheirloom\b', description, re.IGNORECASE):
            types.append('Heirloom')

        return ', '.join(types) if types else None

    def _extract_variations(self) -> List[Dict[str, Any]]:
        """
        Extract size/price variations from product page.

        High Mowing uses a select dropdown for size options with embedded prices.
        """
        variations = []

        try:
            # High Mowing uses a select dropdown for sizes
            # Options are formatted like: "1/2 GRAM - $14.65" or "2 GRAM - $27.95 ( Backordered )"
            size_select = self.page.locator('select[name*="super_attribute"], select#attribute180').first

            if size_select.count() > 0:
                options = size_select.locator('option').all()

                for option in options:
                    option_text = option.text_content() or ''
                    option_value = option.get_attribute('value')

                    # Skip placeholder options
                    if not option_value or option_text.startswith('Choose'):
                        continue

                    variation = self._parse_option_text(option_text)
                    if variation:
                        variations.append(variation)

            # Fallback: try JSON config if select not found
            if not variations:
                variations = self._extract_variations_from_json()

        except Exception as e:
            self.logger.debug(f"Error extracting variations: {e}")

        return variations

    def _parse_option_text(self, option_text: str) -> Optional[Dict[str, Any]]:
        """
        Parse size option text like "1/2 GRAM - $14.65" or "2 GRAM - $27.95 ( Backordered )".
        """
        try:
            # Pattern: SIZE - $PRICE (optional status)
            match = re.match(
                r'^(.+?)\s*-\s*\$([0-9,.]+)\s*(?:\(\s*(.+?)\s*\))?',
                option_text.strip()
            )

            if match:
                size_text = match.group(1).strip()
                price_str = match.group(2).replace(',', '')
                status_text = match.group(3) or ''

                price = float(price_str)

                # Check stock status
                is_in_stock = 'backorder' not in status_text.lower() and 'out of stock' not in status_text.lower()

                # Parse weight
                weight_kg, orig_value, orig_unit = parse_weight_from_string(size_text)

                return {
                    'size': standardize_size_format(size_text),
                    'price': price,
                    'is_variation_in_stock': is_in_stock,
                    'weight_kg': weight_kg,
                    'original_weight_value': orig_value,
                    'original_weight_unit': orig_unit,
                    'sku': None  # SKU not available in dropdown
                }

        except Exception as e:
            self.logger.debug(f"Error parsing option: {option_text} - {e}")

        return None

    def _extract_variations_from_json(self) -> List[Dict[str, Any]]:
        """Fallback: try to extract from Magento JSON config."""
        variations = []

        try:
            scripts = self.page.locator('script:has-text("jsonConfig")').all()

            for script in scripts:
                script_text = script.text_content()
                if not script_text:
                    continue

                json_match = re.search(
                    r'"jsonConfig"\s*:\s*({.*?})\s*[,}]',
                    script_text,
                    re.DOTALL
                )

                if json_match:
                    try:
                        config = json.loads(json_match.group(1))
                        variations = self._parse_magento_config(config)
                        if variations:
                            break
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            self.logger.debug(f"Error extracting JSON config: {e}")

        return variations

    def _parse_magento_config(self, config: Dict) -> List[Dict[str, Any]]:
        """Parse Magento configurable product JSON config."""
        variations = []

        try:
            # Get option prices
            option_prices = config.get('optionPrices', {})
            # Get child products for SKUs
            child_products = config.get('childProducts', {})
            # Get stock info
            stock_info = config.get('stockInfo', {})

            # Get size attribute options
            attributes = config.get('attributes', {})
            size_options = {}

            for attr_id, attr_data in attributes.items():
                if attr_data.get('code') == 'size' or 'size' in attr_data.get('label', '').lower():
                    for option in attr_data.get('options', []):
                        option_id = str(option.get('id'))
                        size_options[option_id] = option.get('label', '')

                        # Get products for this option
                        for prod_id in option.get('products', []):
                            prod_id_str = str(prod_id)

                            # Get price
                            price_data = option_prices.get(prod_id_str, {})
                            final_price = price_data.get('finalPrice', {}).get('amount', 0)

                            # Get SKU
                            child_data = child_products.get(prod_id_str, {})
                            sku = child_data.get('sku', '')

                            # Get stock status
                            stock_data = stock_info.get(prod_id_str, {})
                            in_stock = stock_data.get('is_in_stock', False)

                            if final_price > 0:
                                size_label = option.get('label', 'Unknown')
                                weight_kg, orig_value, orig_unit = parse_weight_from_string(size_label)

                                variations.append({
                                    'size': standardize_size_format(size_label),
                                    'price': float(final_price),
                                    'is_variation_in_stock': in_stock,
                                    'weight_kg': weight_kg,
                                    'original_weight_value': orig_value,
                                    'original_weight_unit': orig_unit,
                                    'sku': sku
                                })

        except Exception as e:
            self.logger.debug(f"Error parsing Magento config: {e}")

        return variations

    def _handle_popups(self) -> None:
        """Handle cookie consent and email popups."""
        try:
            # Cookie consent
            consent_selectors = [
                '#btn-cookie-allow',
                'button:has-text("Accept")',
                '.cookie-consent-accept'
            ]

            for selector in consent_selectors:
                btn = self.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(1)
                    break

            # Email/newsletter modal
            modal_selectors = [
                '.modal-popup .action-close',
                '.newsletter-modal .close',
                '[data-role="closeBtn"]'
            ]

            for selector in modal_selectors:
                btn = self.page.locator(selector).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break

        except Exception as e:
            self.logger.debug(f"Popup handling: {e}")

    def get_politeness_delay(self) -> float:
        """Delay between requests."""
        return 2.0  # Be polite to High Mowing's servers


def main():
    """Run the High Mowing organic scraper."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape organic seeds from High Mowing Organic Seeds"
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

    scraper = HighMowingOrganicScraper(
        test_mode=args.test,
        test_limit=args.limit,
        headless=not args.no_headless
    )
    scraper.run()


if __name__ == "__main__":
    main()
