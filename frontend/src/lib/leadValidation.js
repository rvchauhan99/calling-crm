import { parsePhoneNumberFromString } from "libphonenumber-js"

const EMAIL_RE = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/

export function validatePhone(value) {
  const trimmed = String(value || "").trim().replace(/^[pP]:\s*/, "")
  if (!trimmed) return "Phone is required"
  const parsed = trimmed.startsWith("+")
    ? parsePhoneNumberFromString(trimmed)
    : parsePhoneNumberFromString(trimmed, "IN")
  if (!parsed || !parsed.isValid()) return "Invalid phone number."
  return ""
}

export function validateEmail(value) {
  const trimmed = String(value || "").trim()
  if (!trimmed) return ""
  if (!EMAIL_RE.test(trimmed)) return "Invalid email address"
  return ""
}

export function validateLeadForm(form) {
  const fieldErrors = {}
  const name = String(form.name || "").trim()
  if (!name) fieldErrors.name = "Name is required"
  const phoneErr = validatePhone(form.phone)
  if (phoneErr) fieldErrors.phone = phoneErr
  const emailErr = validateEmail(form.email)
  if (emailErr) fieldErrors.email = emailErr
  if (!form.source) fieldErrors.source = "Source is required"
  return { fieldErrors, isValid: Object.keys(fieldErrors).length === 0 }
}
