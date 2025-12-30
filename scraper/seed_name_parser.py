#!/usr/bin/env python3
import os
import re
import csv
import logging
from seed_naming_utils import parse_seed_name, format_seed_name, load_known_common_names

# Script directory for relative paths
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

WORKSPACE_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
SCRAPER_DATA_DIR = os.path.join(WORKSPACE_ROOT, "scraper_data")
COMMON_NAMES_CSV_FILEPATH = os.path.join(SCRAPER_DATA_DIR, "common_names.csv")

logger = logging.getLogger("SeedNameParser")

# Cache for common names to avoid repeated disk reads
_KNOWN_COMMON_NAMES = None

def get_known_common_names():
    """
    Get known common names from CSV, with caching for performance.
    
    Returns:
        list: List of known common names
    """
    global _KNOWN_COMMON_NAMES
    if _KNOWN_COMMON_NAMES is None:
        if os.path.exists(COMMON_NAMES_CSV_FILEPATH):
            _KNOWN_COMMON_NAMES = load_known_common_names(COMMON_NAMES_CSV_FILEPATH)
        else:
            # Default common names if file doesn't exist
            _KNOWN_COMMON_NAMES = [
                "Alfalfa", "Amaranth", "Arugula", "Barley", "Basil", "Beet", "Bok Choy", "Borage",
                "Broccoli", "Buckwheat", "Cabbage", "Carrot", "Celery", "Chervil", "Chia", "Chicory",
                "Cilantro", "Clover", "Collard", "Coriander", "Corn Salad", "Cress", "Dill",
                "Endive", "Fava Bean", "Fennel", "Fenugreek", "Flax", "Garlic Chives", "Kale",
                "Kamut", "Kohlrabi", "Komatsuna", "Leek", "Lemon Balm", "Lentil", "Lettuce",
                "Mache", "Melon", "Millet", "Mizuna", "Mung Bean", "Mustard", "Nasturtium", "Oat",
                "Okra", "Onion", "Pak Choi", "Parsley", "Pea", "Peppergrass", "Perilla", "Popcorn",
                "Poppy", "Purslane", "Quinoa", "Radish", "Rapini", "Red Shiso", "Rice", "Rocket",
                "Rutabaga", "Rye", "Shiso", "Sorrel", "Spelt", "Spinach", "Sunflower", "Swiss Chard",
                "Tatsoi", "Thyme", "Turnip", "Watercress", "Wheat", "Wheatgrass"
            ]
    return _KNOWN_COMMON_NAMES

def parse_cultivar_and_variety_from_title(title_string):
    """
    Legacy function that parses a product title into common name and cultivar name.
    
    This is a backward-compatible function that maintains the old field names
    but uses the new parsing logic.
    
    Args:
        title_string (str): The product title to parse
        
    Returns:
        dict: Contains 'cultivar' and 'plant_variety' keys for backward compatibility
    """
    if not title_string:
        return {"cultivar": "N/A", "plant_variety": "N/A"}
    
    # Get known common names
    known_common_names = get_known_common_names()
    
    # Parse using the new seed naming utility
    parsed = parse_seed_name(title_string, known_common_names)
    common_name = parsed['common_name']
    cultivar_name = parsed['cultivar_name']
    additional_descriptors = parsed['additional_descriptors']
    
    # Map to the old format for backwards compatibility
    # According to proper naming conventions:
    # - 'cultivar' field should contain the common name (not the cultivar)
    # - 'plant_variety' field should contain the cultivar name
    
    # For compatibility, we'll put the common name in 'cultivar' field
    # and the cultivar name in 'plant_variety' field
    result = {
        "cultivar": common_name,
        "plant_variety": "N/A"
    }
    
    # If we have a cultivar name, use it for plant_variety
    if cultivar_name and cultivar_name != "N/A":
        result["plant_variety"] = cultivar_name
    # If we have additional descriptors but no cultivar, use descriptors as plant_variety
    elif additional_descriptors and additional_descriptors != "N/A":
        result["plant_variety"] = additional_descriptors
    
    return result

def parse_with_proper_naming(title_string):
    """
    Parses a product title with the new field naming convention.
    
    This function replaces 'parse_cultivar_and_variety_from_title' with
    proper field names: 'common_name' and 'cultivar_name'.
    
    Args:
        title_string (str): The product title to parse
        
    Returns:
        dict: Contains 'common_name', 'cultivar_name', and 'additional_descriptors'
    """
    if not title_string:
        return {"common_name": "N/A", "cultivar_name": "N/A", "additional_descriptors": "N/A"}
    
    # Get known common names
    known_common_names = get_known_common_names()
    
    # Parse using the new seed naming utility
    parsed = parse_seed_name(title_string, known_common_names)
    
    return parsed

def parse_title_with_proper_naming(title_string):
    """
    Parses a product title using proper horticultural naming conventions.
    Returns all three components: common name, cultivar name, and additional descriptors.
    
    Args:
        title_string (str): The product title to parse
        
    Returns:
        dict: Contains 'common_name', 'cultivar_name', and 'additional_descriptors'
    """
    known_common_names = get_known_common_names()
    return parse_seed_name(title_string, known_common_names)

def parse_with_botanical_field_names(title_string, category=None):
    """
    Parses a product title and returns results with botanically accurate field names.

    This function is designed to replace the legacy parse_cultivar_and_variety_from_title
    with field names that match botanical terminology.

    Args:
        title_string (str): The product title to parse
        category (str, optional): Category hint (e.g., "Tomatoes", "Amaranths") to use
                                  as fallback common name if not found in title

    Returns:
        dict: Contains 'common_name' and 'cultivar_name' fields matching botanical terminology
    """
    if not title_string:
        return {"common_name": "N/A", "cultivar_name": "N/A"}

    # Get known common names
    known_common_names = get_known_common_names()

    # Parse using the seed naming utility
    parsed = parse_seed_name(title_string, known_common_names)

    common_name = parsed['common_name']
    cultivar_name = parsed['cultivar_name']

    # If common_name looks like it should be a cultivar (not in mapping, title used as-is),
    # try to use category as the common name
    if category and common_name not in known_common_names:
        # Check if common_name is actually the full title or a cultivar-like string
        from seed_naming_utils import COMMON_NAME_MAPPING, standardize_common_name

        # Normalize category (remove trailing 's', lowercase for lookup)
        category_normalized = category.lower().rstrip('s')
        category_with_s = category.lower()

        # Check if category maps to a known common name
        if category_normalized in COMMON_NAME_MAPPING:
            actual_common_name = COMMON_NAME_MAPPING[category_normalized]
            # The parsed common_name is likely the cultivar
            if common_name != "N/A" and common_name != actual_common_name:
                # Use full title minus common name suffix as cultivar
                cultivar_name = common_name
            common_name = actual_common_name
        elif category_with_s in COMMON_NAME_MAPPING:
            actual_common_name = COMMON_NAME_MAPPING[category_with_s]
            if common_name != "N/A" and common_name != actual_common_name:
                cultivar_name = common_name
            common_name = actual_common_name
        elif category.title() in known_common_names:
            actual_common_name = category.title()
            if common_name != "N/A" and common_name != actual_common_name:
                cultivar_name = common_name
            common_name = actual_common_name

    # Clean up cultivar name - remove common name suffix if present
    if cultivar_name != "N/A" and common_name != "N/A":
        import re
        # Remove the common name from the end of cultivar if present
        pattern = re.compile(r'\s*' + re.escape(common_name) + r'\s*$', re.IGNORECASE)
        cultivar_name = pattern.sub('', cultivar_name).strip()
        # Also remove trailing commas, weight info, "Organic" suffix, etc.
        cultivar_name = re.sub(r',?\s*[\d.]+\s*g\s*$', '', cultivar_name).strip()
        cultivar_name = re.sub(r'\s*-\s*Organic\s*$', '', cultivar_name, flags=re.IGNORECASE).strip()
        cultivar_name = re.sub(r'\s*-\s*$', '', cultivar_name).strip()
        if not cultivar_name:
            cultivar_name = "N/A"

    # If we still don't have a good cultivar name but have a title with common name,
    # try to extract cultivar by removing common name from original title
    if title_string and common_name != "N/A":
        import re
        # Remove common name from title to get cultivar
        clean_title = re.sub(r'\s*-\s*Organic\s*$', '', title_string, flags=re.IGNORECASE).strip()
        clean_title = re.sub(r',?\s*[\d.]+\s*g\s*$', '', clean_title).strip()

        # Check if common name is NOT in the title (category-derived)
        if common_name.lower() not in clean_title.lower():
            # The entire clean title is the cultivar name
            if clean_title and clean_title != common_name:
                cultivar_name = clean_title
        elif cultivar_name == "N/A" or cultivar_name == common_name:
            # Common name IS in the title, extract cultivar by removing it
            pattern = re.compile(r'\s*' + re.escape(common_name) + r'\s*$', re.IGNORECASE)
            potential_cultivar = pattern.sub('', clean_title).strip()
            # Also try removing common name from beginning
            pattern2 = re.compile(r'^' + re.escape(common_name) + r'\s*', re.IGNORECASE)
            potential_cultivar = pattern2.sub('', potential_cultivar).strip()
            if potential_cultivar and potential_cultivar != common_name and len(potential_cultivar) > 1:
                cultivar_name = potential_cultivar

    # Return result with the two primary fields only
    result = {
        "common_name": common_name,
        "cultivar_name": cultivar_name
    }

    return result

def format_properly(common_name, cultivar_name, additional_descriptors=None):
    """
    Format a seed name according to proper horticultural naming conventions.
    
    Args:
        common_name (str): The common name
        cultivar_name (str): The cultivar name
        additional_descriptors (str, optional): Additional descriptors
        
    Returns:
        str: Properly formatted seed name
    """
    return format_seed_name(common_name, cultivar_name, additional_descriptors)

if __name__ == "__main__":
    # Example usage
    example_titles = [
        "Ruby Red Lettuce",
        "Kale, Red Russian",
        "Broccoli 'Di Cicco'",
        "Swiss Chard, Bright Lights",
        "Radish 'Daikon' - Organic",
        "4010 Green Forage Pea - Organic",
        "Greencrops, 4010 Green Forage Pea - Organic"
    ]
    
    for title in example_titles:
        # Using the backwards-compatible function
        result_compat = parse_cultivar_and_variety_from_title(title)
        
        # Using the new properly named function
        result_proper = parse_with_proper_naming(title)
        
        print(f"Original: {title}")
        print(f"Backwards compatible: cultivar={result_compat['cultivar']}, plant_variety={result_compat['plant_variety']}")
        print(f"Proper naming: common_name={result_proper['common_name']}, cultivar_name={result_proper['cultivar_name']}, additional_descriptors={result_proper['additional_descriptors']}")
        print(f"Properly formatted: {format_properly(result_proper['common_name'], result_proper['cultivar_name'], result_proper['additional_descriptors'])}")
        print("---") 