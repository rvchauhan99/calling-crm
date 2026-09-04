import { useAuth } from "@/context/AuthContext"
import { cn } from "@/lib/utils"

/** Clickable lead name or phone that opens Lead 360 when user has leads:view. */
export const LeadPhoneLink = ({
  leadId,
  children,
  onOpen,
  className,
  asName = false,
  testId,
}) => {
  const { can } = useAuth()
  const interactive = Boolean(leadId && can("leads:view") && onOpen)

  if (!interactive) {
    return (
      <span className={cn(asName ? "font-medium text-slate-800" : "tabular text-slate-600", className)}>
        {children}
      </span>
    )
  }

  const handleOpen = (e) => {
    e.stopPropagation()
    e.preventDefault()
    onOpen(leadId)
  }

  return (
    <button
      type="button"
      onClick={handleOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          handleOpen(e)
        }
      }}
      className={cn(
        "text-left text-sky-700 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 rounded-sm",
        asName ? "font-medium" : "tabular",
        className,
      )}
      data-testid={testId}
      aria-label={asName ? `Open lead ${children}` : `Open lead ${children}`}
    >
      {children}
    </button>
  )
}
