import { parsePhoneNumberFromString } from "libphonenumber-js"

/** Shown text only. Stored E.164 is unchanged. */
export function formatPhoneDisplay(phone) {
  const raw = String(phone || "")
  if (!raw) return ""
  const parsed = parsePhoneNumberFromString(raw)
  if (!parsed?.countryCallingCode || !parsed.nationalNumber) return raw
  return `+${parsed.countryCallingCode} ${parsed.nationalNumber}`
}
