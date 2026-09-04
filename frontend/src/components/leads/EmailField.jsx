import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function EmailField({ value, onChange, error, testId = "lead-field-email" }) {
  return (
    <div>
      <Label htmlFor="lead-email">Email</Label>
      <Input
        id="lead-email"
        type="email"
        inputMode="email"
        autoComplete="email"
        placeholder="name@example.com (optional)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 focus-visible:ring-sky-500 ${error ? "border-red-400" : ""}`}
        data-testid={testId}
        aria-invalid={!!error}
        aria-describedby={error ? "lead-email-error" : undefined}
      />
      {error && (
        <p id="lead-email-error" className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
