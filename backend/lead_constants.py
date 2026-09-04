"""Shared lead domain constants."""

LEAD_SOURCES = [
    "Website",
    "Facebook Ads",
    "Google Ads",
    "Referral",
    "Cold List",
    "Webinar",
    "Manual",
    "Import",
]

# Sources selectable when creating/editing a lead manually (not Import)
LEAD_SOURCES_CREATABLE = [s for s in LEAD_SOURCES if s != "Import"]
