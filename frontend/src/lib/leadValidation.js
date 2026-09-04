const INDIAN_MOBILE_RE = /^\+91[6-9]\d{9}$/
const INTL_E164_RE = /^\+[1-9]\d{7,14}$/
const EMAIL_RE = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/

function normalizePhoneClient(raw) {
  const s = String(raw || "").trim()
  if (!s) return ""
  const plus = s.startsWith("+")
  const digits = s.replace(/\D/g, "")
  if (!digits) return ""
  if (plus) return `+${digits}`
  if (digits.length === 10) return `+91${digits}`
  if (digits.startsWith("91")) return `+${digits}`
  if (digits.startsWith("0")) return `+91${digits.replace(/^0+/, "")}`
  return `+${digits}`
}

export function validatePhone(value) {
  const trimmed = String(value || "").trim()
  if (!trimmed) return "Phone is required"
  const hadPlus = trimmed.startsWith("+")
  const normalized = normalizePhoneClient(trimmed)
  if (!normalized) return "Invalid phone number. Use 10-digit mobile or +91…"
  if (hadPlus) {
    if (!INTL_E164_RE.test(normalized)) return "Invalid phone number. Use 10-digit mobile or +91…"
  } else if (!INDIAN_MOBILE_RE.test(normalized)) {
    return "Invalid phone number. Use 10-digit mobile or +91…"
  }
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
