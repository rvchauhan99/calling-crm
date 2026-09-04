/** Mirror of backend lead_constants.LEAD_SOURCES */
export const LEAD_SOURCES = [
  "Website",
  "Facebook Ads",
  "Google Ads",
  "Referral",
  "Cold List",
  "Webinar",
  "Manual",
  "Import",
]

export const LEAD_SOURCES_CREATABLE = LEAD_SOURCES.filter((s) => s !== "Import")
