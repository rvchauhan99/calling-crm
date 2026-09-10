"""Default lead-source catalog used only for ensure-on-boot seeding.

Runtime validation reads from the lead_sources Mongo collection.
"""

DEFAULT_LEAD_SOURCES = [
    "Website",
    "Facebook Ads",
    "Google Ads",
    "Referral",
    "Cold List",
    "Webinar",
    "Manual",
    "Import",
]

SYSTEM_LEAD_SOURCES = {"Manual", "Import"}
NON_CREATABLE_LEAD_SOURCES = {"Import"}

# Backward-compatible aliases (demo seed / tests may still import these names)
LEAD_SOURCES = DEFAULT_LEAD_SOURCES
LEAD_SOURCES_CREATABLE = [s for s in DEFAULT_LEAD_SOURCES if s not in NON_CREATABLE_LEAD_SOURCES]
