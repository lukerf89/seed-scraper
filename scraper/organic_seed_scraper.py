"""
Base class for organic seed scrapers with USDA NOP compliance features.

Extends PageNavigationScraper to add:
- Organic-only product filtering
- Seed treatment detection
- Enhanced data schema for organic recordkeeping
"""

from abc import abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
import os
import json
import time

from base_scraper import PageNavigationScraper
from organic_detection import (
    OrganicDetector, SeedTreatmentDetector,
    OrganicDetectionResult, SeedTreatmentInfo
)
from scraper_utils import setup_logging
from seed_name_parser import parse_with_botanical_field_names


class OrganicSeedScraper(PageNavigationScraper):
    """
    Base class for organic seed scrapers with NOP compliance.

    Features:
    - Filters products to only include certified organic seeds
    - Detects and records seed treatment information
    - Captures supplier and certification details
    - Outputs enhanced schema for organic recordkeeping
    """

    # Subclasses should override these
    SUPPLIER_NAME = "Unknown Supplier"
    SUPPLIER_WEBSITE = "https://example.com"
    CURRENCY_CODE = "USD"

    def __init__(
        self,
        output_dir: str = "./scraper_data/json_files/organic",
        headless: bool = True,
        test_mode: bool = False,
        test_limit: int = 3
    ):
        """
        Initialize organic seed scraper.

        Args:
            output_dir: Directory for output files
            headless: Run browser in headless mode
            test_mode: Limit scraping for testing
            test_limit: Number of products in test mode
        """
        # Create supplier-specific output directory
        supplier_dir = self.SUPPLIER_NAME.lower().replace(' ', '_').replace("'", '')
        full_output_dir = os.path.join(output_dir, supplier_dir)

        super().__init__(
            supplier_name=self.SUPPLIER_NAME,
            source_site=self.SUPPLIER_WEBSITE,
            output_dir=full_output_dir,
            currency_code=self.CURRENCY_CODE,
            headless=headless,
            test_mode=test_mode,
            test_limit=test_limit
        )

        # Initialize organic detection tools
        self.organic_detector = OrganicDetector()
        self.treatment_detector = SeedTreatmentDetector()

        # Statistics tracking
        self.stats = {
            'total_found': 0,
            'organic_count': 0,
            'non_organic_skipped': 0,
            'treatment_detected': 0,
            'treatment_unknown': 0
        }

    def fetch_product_list(self) -> List[Dict[str, Any]]:
        """
        Fetch and filter product list for organic-only products.

        Returns:
            List of organic product dictionaries
        """
        # Get all products from parent implementation
        all_products = super().fetch_product_list()
        self.stats['total_found'] = len(all_products)

        # Filter for organic products only
        organic_products = []
        for product in all_products:
            # Check if organic_status was pre-set by subclass (e.g., from URL filter)
            if product.get('organic_status', {}).get('is_certified_organic'):
                # Trust pre-set organic status from source filter
                organic_products.append(product)
                self.stats['organic_count'] += 1
                self.logger.debug(f"Organic (source filter): {product.get('title')}")
            else:
                # Run organic detection for products without pre-set status
                organic_result = self._check_organic_status(product)
                if organic_result.is_organic:
                    product['organic_status'] = {
                        'is_certified_organic': True,
                        'certification_type': organic_result.certification_type or 'USDA Organic',
                        'confidence': organic_result.confidence,
                        'indicators_found': organic_result.indicators_found,
                        'non_gmo_verified': organic_result.non_gmo_verified
                    }
                    organic_products.append(product)
                    self.stats['organic_count'] += 1
                else:
                    self.stats['non_organic_skipped'] += 1
                    self.logger.debug(f"Skipping non-organic: {product.get('title')}")

        self.logger.info(
            f"Filtered {len(organic_products)} organic products "
            f"from {len(all_products)} total ({self.stats['non_organic_skipped']} skipped)"
        )

        return organic_products

    def _check_organic_status(self, product: Dict[str, Any]) -> OrganicDetectionResult:
        """
        Check if a product is organic using enhanced detection.

        Args:
            product: Product dictionary with at least 'title'

        Returns:
            OrganicDetectionResult
        """
        title = product.get('title', '')
        description = product.get('description', '')

        return self.organic_detector.detect(
            title=title,
            description=description
        )

    def scrape_product_details(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape detailed information including treatment info.

        Subclasses should call super() and then add their own details.

        Args:
            product: Product dictionary from fetch_product_list

        Returns:
            Enhanced product dictionary with organic fields
        """
        # Start with the product data
        detailed = product.copy()

        # Add supplier information
        detailed['supplier'] = {
            'name': self.SUPPLIER_NAME,
            'website': self.SUPPLIER_WEBSITE
        }

        # Parse botanical name if not already done
        if 'common_name' not in detailed:
            parsed = parse_with_botanical_field_names(product.get('title', ''))
            detailed['common_name'] = parsed.get('common_name', 'Unknown')
            detailed['cultivar_name'] = parsed.get('cultivar_name', 'N/A')

        # Add scrape timestamp
        detailed['scrape_timestamp'] = datetime.now().isoformat()

        return detailed

    def _extract_treatment_info(
        self,
        title: str,
        description: str = "",
        product_details: Dict = None
    ) -> Dict[str, Any]:
        """
        Extract seed treatment information.

        Args:
            title: Product title
            description: Product description
            product_details: Additional product details

        Returns:
            Treatment info dictionary
        """
        treatment = self.treatment_detector.detect(
            title=title,
            description=description,
            product_details=product_details
        )

        # Update stats
        if treatment.confidence in ['high', 'medium']:
            self.stats['treatment_detected'] += 1
        else:
            self.stats['treatment_unknown'] += 1

        return {
            'has_treatment': treatment.has_treatment,
            'treatment_type': treatment.treatment_type,
            'treatment_details': treatment.treatment_details,
            'is_organic_approved': treatment.is_organic_approved,
            'detection_confidence': treatment.confidence,
            'info_source': treatment.source
        }

    def _get_product_description(self) -> str:
        """
        Get product description from current page.

        Subclasses should override with site-specific selectors.

        Returns:
            Product description text
        """
        try:
            # Common description selectors
            selectors = [
                '.product-description',
                '.description',
                '#description',
                '[data-description]',
                '.product-details',
                '.product-info'
            ]

            for selector in selectors:
                elem = self.page.locator(selector).first
                if elem.count() > 0:
                    return elem.text_content() or ""

        except Exception as e:
            self.logger.debug(f"Error getting description: {e}")

        return ""

    def _get_product_details_section(self) -> Dict[str, str]:
        """
        Get structured product details from current page.

        Subclasses should override with site-specific parsing.

        Returns:
            Dictionary of detail key-value pairs
        """
        return {}

    def save_results(
        self,
        products: List[Dict[str, Any]],
        filename_prefix: Optional[str] = None
    ) -> str:
        """
        Save results with enhanced organic metadata.

        Args:
            products: List of product dictionaries
            filename_prefix: Optional filename prefix

        Returns:
            Path to saved file
        """
        # Create output directory if needed
        os.makedirs(self.output_dir, exist_ok=True)

        # Generate filename
        timestamp = datetime.now()
        filename = f"organic_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.output_dir, filename)

        # Build output structure
        duration = time.time() - self.start_time if self.start_time else 0

        output = {
            'metadata': {
                'timestamp': timestamp.isoformat(),
                'scrape_duration_seconds': round(duration, 2),
                'scraper_version': '1.0.0-organic',
                'purpose': 'USDA_NOP_recordkeeping'
            },
            'supplier_info': {
                'name': self.SUPPLIER_NAME,
                'website': self.SUPPLIER_WEBSITE,
                'currency_code': self.CURRENCY_CODE
            },
            'filter_settings': {
                'organic_only': True
            },
            'summary': {
                'total_products_found': self.stats['total_found'],
                'organic_products_scraped': len(products),
                'non_organic_skipped': self.stats['non_organic_skipped'],
                'products_with_treatment_info': self.stats['treatment_detected'],
                'products_missing_treatment_info': self.stats['treatment_unknown']
            },
            'products': products
        }

        # Write JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Saved {len(products)} organic products to {filepath}")
        return filepath

    def run(self) -> None:
        """
        Run the organic scraper with statistics reporting.
        """
        with self:
            products = self.scrape()
            if products:
                output_file = self.save_results(products)
                self.logger.info(
                    f"\n{'='*50}\n"
                    f"Organic Scrape Complete\n"
                    f"{'='*50}\n"
                    f"Supplier: {self.SUPPLIER_NAME}\n"
                    f"Total found: {self.stats['total_found']}\n"
                    f"Organic scraped: {len(products)}\n"
                    f"Non-organic skipped: {self.stats['non_organic_skipped']}\n"
                    f"Treatment info found: {self.stats['treatment_detected']}\n"
                    f"Treatment unknown: {self.stats['treatment_unknown']}\n"
                    f"Output: {output_file}\n"
                    f"{'='*50}"
                )
            else:
                self.logger.warning("No organic products were scraped")
