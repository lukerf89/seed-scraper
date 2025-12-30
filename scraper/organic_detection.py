"""
Organic detection and seed treatment analysis for USDA NOP compliance.

This module provides classes for detecting organic certification status
and analyzing seed treatments for organic recordkeeping purposes.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import re


@dataclass
class OrganicDetectionResult:
    """Result of organic product detection."""
    is_organic: bool
    confidence: str  # "high", "medium", "low"
    indicators_found: List[str]
    certification_type: Optional[str]
    non_gmo_verified: bool
    warnings: List[str]


@dataclass
class SeedTreatmentInfo:
    """Information about seed treatment and NOP compliance."""
    has_treatment: bool
    treatment_type: str  # Untreated, Primed, Pelleted, Coated, Fungicide, etc.
    treatment_details: Optional[str]
    is_organic_approved: bool
    confidence: str  # "high", "medium", "low", "unknown"
    source: str  # Where the info was found (title, description, details, etc.)


class OrganicDetector:
    """
    Enhanced organic product detection for USDA NOP compliance.

    Goes beyond simple keyword matching to analyze multiple signals
    and provide confidence levels.
    """

    # Positive organic indicators (prioritized by confidence)
    HIGH_CONFIDENCE_KEYWORDS = [
        'certified organic',
        'usda organic',
        'nop certified',
        'organically grown',
        'usda certified organic'
    ]

    MEDIUM_CONFIDENCE_KEYWORDS = [
        'organic',
        'biologique',  # French
        'organico',    # Spanish
    ]

    # Keywords that indicate NOT organic
    CONVENTIONAL_INDICATORS = [
        'conventional',
        'non-organic',
        'treated seed',
        'fungicide treated',
        'thiram treated',
        'captan treated'
    ]

    # Non-GMO indicators (separate from organic but often appears together)
    NON_GMO_KEYWORDS = [
        'non-gmo',
        'non gmo',
        'nongmo',
        'non-gmo project verified',
        'gmo-free'
    ]

    # Certification types we can detect
    CERTIFICATION_PATTERNS = {
        'USDA Organic': [r'\bUSDA\s*Organic\b', r'\bUSDA\s*Certified\b'],
        'NOP Certified': [r'\bNOP\b', r'National\s*Organic\s*Program'],
        'Certified Organic': [r'\bCertified\s*Organic\b'],
    }

    def detect(
        self,
        title: str,
        description: str = "",
        page_content: str = "",
        badges: List[str] = None
    ) -> OrganicDetectionResult:
        """
        Analyze product information to determine organic status.

        Args:
            title: Product title
            description: Product description text
            page_content: Full page content for additional context
            badges: List of detected badge/certification texts

        Returns:
            OrganicDetectionResult with detection details
        """
        badges = badges or []
        combined_text = f"{title} {description} {page_content} {' '.join(badges)}".lower()

        # Check for conventional indicators first (exclusion)
        for indicator in self.CONVENTIONAL_INDICATORS:
            if indicator in combined_text:
                return OrganicDetectionResult(
                    is_organic=False,
                    confidence="high",
                    indicators_found=[f"conventional: {indicator}"],
                    certification_type=None,
                    non_gmo_verified=self._check_non_gmo(combined_text),
                    warnings=["Product appears to be conventional/treated"]
                )

        # Check for high-confidence organic keywords
        indicators_found = []
        confidence = "low"

        for keyword in self.HIGH_CONFIDENCE_KEYWORDS:
            if keyword in combined_text:
                indicators_found.append(keyword)
                confidence = "high"

        # Check medium-confidence keywords if no high-confidence found
        if not indicators_found:
            for keyword in self.MEDIUM_CONFIDENCE_KEYWORDS:
                # Use word boundary matching to avoid false positives
                pattern = rf'\b{re.escape(keyword)}\b'
                if re.search(pattern, combined_text):
                    indicators_found.append(keyword)
                    confidence = "medium"

        # Detect certification type
        certification_type = self._detect_certification_type(combined_text)
        if certification_type:
            confidence = "high"

        # Check Non-GMO status
        non_gmo_verified = self._check_non_gmo(combined_text)

        # Build warnings
        warnings = []
        if indicators_found and confidence == "medium":
            warnings.append("Organic status based on keyword only - verify certification")

        is_organic = len(indicators_found) > 0

        return OrganicDetectionResult(
            is_organic=is_organic,
            confidence=confidence if is_organic else "n/a",
            indicators_found=indicators_found,
            certification_type=certification_type,
            non_gmo_verified=non_gmo_verified,
            warnings=warnings
        )

    def _detect_certification_type(self, text: str) -> Optional[str]:
        """Detect specific certification type from text."""
        for cert_type, patterns in self.CERTIFICATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return cert_type
        return None

    def _check_non_gmo(self, text: str) -> bool:
        """Check for Non-GMO verification."""
        for keyword in self.NON_GMO_KEYWORDS:
            if keyword in text:
                return True
        return False


class SeedTreatmentDetector:
    """
    Detect and classify seed treatments for NOP compliance.

    Critical for organic recordkeeping as treated seeds may not be
    permitted under organic certification.
    """

    # Organic-approved treatments (allowed under NOP)
    ORGANIC_APPROVED_TREATMENTS = {
        'untreated': ['untreated', 'no treatment', 'not treated', 'raw seed'],
        'hot_water': ['hot water treated', 'hot water treatment', 'hwt'],
        'organic_primed': ['organic primed', 'organically primed'],
        'organic_pelleted': ['organic pelleted', 'organically pelleted', 'organic pellet'],
        'organic_coated': ['organic coated', 'organically coated', 'organic film coat'],
        'inoculated': ['rhizobium inoculated', 'inoculated', 'nitrogen fixing bacteria'],
    }

    # Prohibited treatments (NOT allowed under NOP for organic production)
    PROHIBITED_TREATMENTS = {
        'fungicide': ['fungicide treated', 'fungicide', 'fungicidal'],
        'thiram': ['thiram', 'thiram treated'],
        'captan': ['captan', 'captan treated'],
        'fludioxonil': ['fludioxonil', 'maxim'],
        'mefenoxam': ['mefenoxam', 'metalaxyl', 'apron'],
        'neonicotinoid': ['neonicotinoid', 'imidacloprid', 'clothianidin', 'thiamethoxam'],
        'insecticide': ['insecticide treated', 'insecticide'],
        'conventional_treatment': ['conventional treatment', 'conventionally treated'],
    }

    # Treatment types that need further investigation
    AMBIGUOUS_TREATMENTS = {
        'primed': ['primed', 'seed priming'],  # Could be organic or conventional
        'pelleted': ['pelleted', 'pellet', 'pelleting'],
        'coated': ['coated', 'film coated', 'seed coating'],
        'encrustred': ['encrusted'],
    }

    # Patterns to extract treatment details
    TREATMENT_DETAIL_PATTERNS = [
        r'treatment[:\s]+([^.;]+)',
        r'seed\s+treatment[:\s]+([^.;]+)',
        r'coating[:\s]+([^.;]+)',
        r'treated\s+with[:\s]+([^.;]+)',
    ]

    def detect(
        self,
        title: str,
        description: str = "",
        product_details: Dict = None
    ) -> SeedTreatmentInfo:
        """
        Detect seed treatment information from product data.

        Args:
            title: Product title
            description: Product description
            product_details: Additional product details dict

        Returns:
            SeedTreatmentInfo with treatment analysis
        """
        product_details = product_details or {}

        # Combine all text sources
        combined_text = f"{title} {description}".lower()
        if product_details:
            combined_text += " " + " ".join(str(v).lower() for v in product_details.values())

        # Check for explicit "untreated" first (most common for organic)
        for treatment_type, keywords in self.ORGANIC_APPROVED_TREATMENTS.items():
            for keyword in keywords:
                if keyword in combined_text:
                    return SeedTreatmentInfo(
                        has_treatment=(treatment_type != 'untreated'),
                        treatment_type=treatment_type.replace('_', ' ').title(),
                        treatment_details=self._extract_treatment_details(combined_text),
                        is_organic_approved=True,
                        confidence="high",
                        source=self._determine_source(title, description, keyword)
                    )

        # Check for prohibited treatments
        for treatment_type, keywords in self.PROHIBITED_TREATMENTS.items():
            for keyword in keywords:
                if keyword in combined_text:
                    return SeedTreatmentInfo(
                        has_treatment=True,
                        treatment_type=treatment_type.replace('_', ' ').title(),
                        treatment_details=self._extract_treatment_details(combined_text),
                        is_organic_approved=False,
                        confidence="high",
                        source=self._determine_source(title, description, keyword)
                    )

        # Check for ambiguous treatments
        for treatment_type, keywords in self.AMBIGUOUS_TREATMENTS.items():
            for keyword in keywords:
                if keyword in combined_text:
                    # Check if it's explicitly organic
                    is_organic = 'organic' in combined_text and keyword in combined_text
                    return SeedTreatmentInfo(
                        has_treatment=True,
                        treatment_type=treatment_type.title(),
                        treatment_details=self._extract_treatment_details(combined_text),
                        is_organic_approved=is_organic,
                        confidence="medium" if is_organic else "low",
                        source=self._determine_source(title, description, keyword)
                    )

        # No treatment info found - for organic products, often means untreated
        return SeedTreatmentInfo(
            has_treatment=False,
            treatment_type="Unknown",
            treatment_details=None,
            is_organic_approved=True,  # Assume approved if no treatment info
            confidence="unknown",
            source="not_found"
        )

    def _extract_treatment_details(self, text: str) -> Optional[str]:
        """Extract specific treatment details from text."""
        for pattern in self.TREATMENT_DETAIL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:100]  # Limit length
        return None

    def _determine_source(self, title: str, description: str, keyword: str) -> str:
        """Determine which source contained the treatment info."""
        if keyword in title.lower():
            return "title"
        elif keyword in description.lower():
            return "description"
        else:
            return "details"


def is_organic_product_enhanced(
    title: str,
    description: str = "",
    page_content: str = ""
) -> Tuple[bool, OrganicDetectionResult]:
    """
    Convenience function for enhanced organic detection.

    Args:
        title: Product title
        description: Product description
        page_content: Full page content

    Returns:
        Tuple of (is_organic, detection_result)
    """
    detector = OrganicDetector()
    result = detector.detect(title, description, page_content)
    return result.is_organic, result


def get_treatment_info(
    title: str,
    description: str = "",
    product_details: Dict = None
) -> SeedTreatmentInfo:
    """
    Convenience function to get seed treatment info.

    Args:
        title: Product title
        description: Product description
        product_details: Additional details dict

    Returns:
        SeedTreatmentInfo object
    """
    detector = SeedTreatmentDetector()
    return detector.detect(title, description, product_details)
