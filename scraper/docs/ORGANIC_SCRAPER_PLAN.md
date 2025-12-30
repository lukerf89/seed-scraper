# Organic Seed Scraper Implementation Plan

## Goal
Modify the seed-scraper to create a comprehensive database of **certified organic seed varieties** for USDA NOP recordkeeping, starting with Johnny's Seeds and expanding to High Mowing, Fedco, and Southern Exposure.

## Requirements Summary
- **USDA NOP compliance**: Capture all fields needed for organic certification audits
- **Organic-only scraping**: Filter to only certified organic products
- **Seed treatments**: Capture coating/treatment info and whether it's organic-approved
- **Target suppliers**: Johnny's Seeds → High Mowing → Fedco → Southern Exposure

---

## New Data Schema for Organic Recordkeeping

```python
{
    "supplier": {
        "name": "Johnny's Selected Seeds",
        "website": "https://johnnyseeds.com"
    },
    "product_name": "Leek Organic Microgreen Seed",
    "common_name": "Leek",
    "cultivar_name": "N/A",
    "sku": "5061MG",
    "product_url": "https://...",

    # Organic certification
    "organic_status": {
        "is_certified_organic": true,
        "certification_type": "USDA Organic",
        "indicators_found": ["Organic"]
    },

    # Seed treatment (critical for NOP)
    "seed_treatment": {
        "has_treatment": false,
        "treatment_type": "Untreated",
        "treatment_details": null,
        "is_organic_approved": true
    },

    # Lot info for traceability
    "lot_info": {
        "lot_number": null,
        "germination_rate": "85%"
    },

    "is_in_stock": true,
    "variations": [...]
}
```

---

## Implementation Steps

### Phase 1: Core Infrastructure

#### Step 1.1: Create `organic_detection.py`
New module with enhanced organic and treatment detection.

#### Step 1.2: Create `organic_seed_scraper.py`
New base class extending `PageNavigationScraper`.

---

### Phase 2: Johnny's Seeds Organic Scraper

Create `organic_johnnyseeds_scraper.py` with:
1. Organic-filtered URLs: `?prefn1=Organic&prefv1=true`
2. Treatment detection from product descriptions
3. Organic certification badge extraction
4. New organic schema output

---

### Phase 3: Additional Supplier Scrapers

- **High Mowing** (`highmowing_scraper.py`) - 100% organic catalog
- **Fedco** (`fedco_scraper.py`) - Use `/seeds/list-organic` filter
- **Southern Exposure** (`southernexposure_scraper.py`) - Mixed catalog

---

## Files to Create

| File | Purpose |
|------|---------|
| `organic_detection.py` | `OrganicDetector` and `SeedTreatmentDetector` classes |
| `organic_seed_scraper.py` | `OrganicSeedScraper` base class |
| `organic_johnnyseeds_scraper.py` | Johnny's organic scraper |

---

## Treatment Detection Keywords

- **Untreated/Organic-approved**: "untreated", "organic primed", "hot water treated"
- **Prohibited**: "thiram", "captan", "fungicide treated", "conventional"
