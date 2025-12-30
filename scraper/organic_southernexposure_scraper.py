#!/usr/bin/env python3
"""
Southern Exposure Seed Exchange organic seed scraper for USDA NOP recordkeeping.

Scrapes certified organic seeds from Southern Exposure's catalog,
filtering for products with organic certification badges.
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


class SouthernExposureOrganicScraper(OrganicSeedScraper):
    """
    Organic seed scraper for Southern Exposure Seed Exchange.

    Southern Exposure has a mixed catalog with organic and conventional seeds.
    This scraper filters for products with the organic certification badge.
    """

    # Supplier configuration
    SUPPLIER_NAME = "Southern Exposure Seed Exchange"
    SUPPLIER_WEBSITE = "https://www.southernexposure.com"
    CURRENCY_CODE = "USD"

    # Category URLs to scrape
    CATEGORY_URLS = [
        "https://www.southernexposure.com/categories/tomatoes/",
        # Can add more categories:
        # "https://www.southernexposure.com/categories/peppers/",
        # "https://www.southernexposure.com/categories/lettuce/",
        # "https://www.southernexposure.com/categories/beans/",
    ]

    def __init__(
        self,
        categories: List[str] = None,
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 3
    ):
        """
        Initialize Southern Exposure organic scraper.

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
        """Get category URLs."""
        return self.category_urls

    def extract_product_links(self, page_url: str) -> List[Dict[str, Any]]:
        """
        Extract organic product links from category page.

        Args:
            page_url: URL of the category page

        Returns:
            List of product dictionaries (organic only)
        """
        self.logger.info(f"Extracting product links from: {page_url}")
        products = []

        try:
            # Navigate to page
            self.page.goto(page_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            # Wait for products to load
            try:
                self.page.wait_for_selector('[itemtype*="schema.org/Product"]', timeout=10000)
            except PlaywrightTimeoutError:
                self.logger.warning("No products found on page")
                return products

            # Extract product cards
            cards = self.page.locator('[itemtype*="schema.org/Product"]').all()
            self.logger.info(f"Found {len(cards)} product cards")

            for card in cards:
                try:
                    product = self._extract_product_from_card(card)
                    if product:
                        products.append(product)
                except Exception as e:
                    self.logger.debug(f"Error extracting card: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error extracting products: {e}")

        self.logger.info(f"Extracted {len(products)} organic products")
        return products

    def _extract_product_from_card(self, card) -> Optional[Dict[str, Any]]:
        """Extract product info from a product card, only if organic."""
        # Check for organic certification badge (green leaf SVG)
        # The organic badge has fill="#279240" and tooltip "Certified Organic"
        organic_indicators = [
            'svg path[fill="#279240"]',
            '[id*="Certified Organic"]',
            '[title*="organic" i]'
        ]

        is_organic = False
        for selector in organic_indicators:
            if card.locator(selector).count() > 0:
                is_organic = True
                break

        if not is_organic:
            return None  # Skip non-organic products

        # Get product URL
        link = card.locator('a[href*="/products/"]').first
        if link.count() == 0:
            return None

        href = link.get_attribute('href')
        if not href:
            return None

        url = make_absolute_url(href, self.SUPPLIER_WEBSITE)

        # Get product name from schema.org markup
        name_elem = card.locator('[itemprop="name"]').first
        if name_elem.count() == 0:
            return None

        # Get the text content from the name element
        title = ''
        name_text = name_elem.text_content()
        if name_text:
            title = clean_text(name_text)

        if not title:
            return None

        # Get SKU
        sku_elem = card.locator('[itemprop="sku"]').first
        sku = ''
        if sku_elem.count() > 0:
            sku = sku_elem.get_attribute('content') or ''

        # Get item number from description
        item_elem = card.locator('small:has-text("Item #"), p:has-text("Item #")').first
        item_number = sku
        if item_elem.count() > 0:
            item_text = item_elem.text_content()
            match = re.search(r'Item #(\d+)', item_text)
            if match:
                item_number = match.group(1)

        # Check for heirloom badge
        is_heirloom = card.locator('[id*="Heirloom"]').count() > 0

        # Parse botanical name
        parsed = parse_with_botanical_field_names(title)

        return {
            'title': title,
            'url': url,
            'sku': item_number,
            'common_name': parsed.get('common_name', 'Unknown'),
            'cultivar_name': parsed.get('cultivar_name', 'N/A'),
            'is_heirloom': is_heirloom,
            'organic_status': {
                'is_certified_organic': True,
                'certification_type': 'Certified Organic by Quality Certification Services',
                'confidence': 'high',
                'indicators_found': ['organic_badge'],
                'non_gmo_verified': False
            }
        }

    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed product information.

        Args:
            product: Basic product info

        Returns:
            Complete product dictionary with organic fields
        """
        self.logger.info(f"Scraping details for: {product['title']}")

        # Get base details from parent
        detailed = super().scrape_product_details(product)

        # Copy over extra fields
        detailed['is_heirloom'] = product.get('is_heirloom', False)

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

            # Extract days to maturity from description
            detailed['days_to_maturity'] = self._extract_days_to_maturity(description)

            # Extract plant type
            detailed['plant_type'] = self._extract_plant_type(description)

            # Extract variations from schema.org offers
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
            desc_elem = self.page.locator('[itemprop="description"]').first
            if desc_elem.count() > 0:
                text = desc_elem.text_content()
                if text:
                    return clean_text(text)

            # Fallback to other selectors
            selectors = [
                '.product-description',
                '.description',
                'article p',
                '.static-page p'
            ]

            for selector in selectors:
                elem = self.page.locator(selector).first
                if elem.count() > 0:
                    text = elem.text_content()
                    if text and len(text.strip()) > 20:
                        return clean_text(text)

        except Exception as e:
            self.logger.debug(f"Error getting description: {e}")

        return ""

    def _get_product_details_section(self) -> Dict[str, str]:
        """Extract product details/specs section."""
        details = {}

        try:
            # Southern Exposure includes details in the description
            desc = self._get_product_description()

            # Extract disease resistance codes
            resistance_match = re.search(r'\(([a-z, ]+)\)', desc)
            if resistance_match:
                details['disease_resistance'] = resistance_match.group(1)

            # Extract growth habit
            if 'indeterminate' in desc.lower():
                details['growth_habit'] = 'Indeterminate'
            elif 'determinate' in desc.lower():
                details['growth_habit'] = 'Determinate'

        except Exception as e:
            self.logger.debug(f"Error getting details: {e}")

        return details

    def _extract_days_to_maturity(self, description: str) -> Optional[str]:
        """Extract days to maturity from description."""
        # Southern Exposure typically starts description with "XX days."
        patterns = [
            r'^(\d+)\s*days?\.',
            r'(\d+)\s*(?:to\s*\d+)?\s*days?\s*(?:to\s*)?(?:maturity|harvest)',
            r'matures?\s*in\s*(\d+)\s*days?',
        ]

        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(1) + " days"
        return None

    def _extract_plant_type(self, description: str) -> Optional[str]:
        """Extract plant type from description."""
        types = []

        if re.search(r'\bindeterminate\b', description, re.IGNORECASE):
            types.append('Indeterminate')
        elif re.search(r'\bdeterminate\b', description, re.IGNORECASE):
            types.append('Determinate')

        if re.search(r'\bopen[- ]pollinated\b|\bOP\b', description, re.IGNORECASE):
            types.append('Open-Pollinated')
        elif re.search(r'\bhybrid\b|\bF1\b', description, re.IGNORECASE):
            types.append('Hybrid')

        return ', '.join(types) if types else None

    def _extract_variations(self) -> List[Dict[str, Any]]:
        """
        Extract size/price variations from product page.

        Southern Exposure uses schema.org Offer markup for variations.
        """
        variations = []

        try:
            # Find all offers in schema.org markup
            offers = self.page.locator('[itemprop="offers"]').all()

            for offer in offers:
                try:
                    # Get SKU
                    sku_elem = offer.locator('[itemprop="sku"]').first
                    sku = sku_elem.get_attribute('content') if sku_elem.count() > 0 else ''

                    # Get price
                    price_elem = offer.locator('[itemprop="price"]').first
                    price_str = price_elem.get_attribute('content') if price_elem.count() > 0 else '0'
                    price = float(price_str)

                    # Get size from description
                    desc_elem = offer.locator('[itemprop="description"]').first
                    size_text = desc_elem.get_attribute('content') if desc_elem.count() > 0 else ''

                    # Get availability
                    avail_elem = offer.locator('[itemprop="availability"]').first
                    avail = avail_elem.get_attribute('content') if avail_elem.count() > 0 else ''
                    is_in_stock = 'InStock' in avail

                    if price > 0 and size_text:
                        # Parse weight
                        weight_kg, orig_value, orig_unit = parse_weight_from_string(size_text)

                        variations.append({
                            'size': standardize_size_format(size_text),
                            'price': price,
                            'is_variation_in_stock': is_in_stock,
                            'weight_kg': weight_kg,
                            'original_weight_value': orig_value,
                            'original_weight_unit': orig_unit,
                            'sku': sku
                        })

                except Exception as e:
                    self.logger.debug(f"Error parsing offer: {e}")
                    continue

        except Exception as e:
            self.logger.debug(f"Error extracting variations: {e}")

        return variations

    def get_politeness_delay(self) -> float:
        """Delay between requests."""
        return 2.0


def main():
    """Run the Southern Exposure organic scraper."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape organic seeds from Southern Exposure Seed Exchange"
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

    scraper = SouthernExposureOrganicScraper(
        test_mode=args.test,
        test_limit=args.limit,
        headless=not args.no_headless
    )
    scraper.run()


if __name__ == "__main__":
    main()
