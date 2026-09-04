import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function PhoneField({ value, onChange, error, testId = "lead-field-phone" }) {
  const handleChange = (e) => {
    const next = e.target.value.replace(/[^\d+\s\-()]/g, "")
    onChange(next)
  }

  return (
    <div>
      <Label htmlFor="lead-phone">Phone</Label>
      <Input
        id="lead-phone"
        type="tel"
        inputMode="numeric"
        autoComplete="tel"
        placeholder="10-digit mobile"
        value={value}
        onChange={handleChange}
        className={`mt-1 focus-visible:ring-sky-500 ${error ? "border-red-400" : ""}`}
        data-testid={testId}
        aria-invalid={!!error}
        aria-describedby={error ? "lead-phone-error" : undefined}
      />
      {error && (
        <p id="lead-phone-error" className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
