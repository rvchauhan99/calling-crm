import { useEffect, useState } from "react"
import { getCountryCallingCode, parsePhoneNumberFromString } from "libphonenumber-js"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PhoneCountrySelect } from "@/components/filters/CountrySelect"

function splitPhone(value) {
  const raw = String(value || "").trim()
  if (!raw) return { country: "IN", national: "" }
  const parsed = parsePhoneNumberFromString(raw.startsWith("+") ? raw : raw, raw.startsWith("+") ? undefined : "IN")
  if (parsed) {
    return { country: parsed.country || "IN", national: parsed.nationalNumber || "" }
  }
  return { country: "IN", national: raw.replace(/\D/g, "") }
}

export function PhoneField({ value, onChange, error, testId = "lead-field-phone" }) {
  const [country, setCountry] = useState("IN")
  const [national, setNational] = useState("")

  useEffect(() => {
    const next = splitPhone(value)
    setCountry(next.country)
    setNational(next.national)
  }, [value])

  const emit = (nextCountry, nextNational) => {
    const digits = String(nextNational || "").replace(/\D/g, "")
    if (!digits) {
      onChange("")
      return
    }
    const code = getCountryCallingCode(nextCountry || "IN")
    onChange(`+${code}${digits}`)
  }

  return (
    <div>
      <Label htmlFor="lead-phone">Phone</Label>
      <div className="mt-1 flex gap-2">
        <PhoneCountrySelect
          value={country}
          onChange={(next) => {
            setCountry(next)
            emit(next, national)
          }}
        />
        <Input
          id="lead-phone"
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          placeholder="National number"
          value={national}
          onChange={(e) => {
            const next = e.target.value.replace(/[^\d\s\-()]/g, "")
            setNational(next)
            emit(country, next)
          }}
          className={`focus-visible:ring-sky-500 ${error ? "border-red-400" : ""}`}
          data-testid={testId}
          aria-invalid={!!error}
          aria-describedby={error ? "lead-phone-error" : undefined}
        />
      </div>
      {error && (
        <p id="lead-phone-error" className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function PhoneWithCountry({ phone, country, testId }) {
  return (
    <span data-testid={testId}>
      {country ? <span className="mr-1 text-xs font-medium text-slate-500">{country}</span> : null}
      <span className="tabular">{phone}</span>
    </span>
  )
}
