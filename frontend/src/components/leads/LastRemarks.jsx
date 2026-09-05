/**
 * Truncated display of a lead's last call-log remarks (API: last_notes).
 */
export const LastRemarks = ({
  notes,
  compact = false,
  showLabel = false,
  empty = "—",
  testId = "last-remarks",
  className = "",
}) => {
  const text = typeof notes === "string" ? notes.trim() : ""
  const hasNotes = Boolean(text)

  if (!hasNotes && !showLabel) {
    return (
      <span
        className={`text-slate-300 ${className}`}
        data-testid={testId}
        title=""
      >
        {empty}
      </span>
    )
  }

  const body = hasNotes ? (
    <span
      className={
        compact
          ? "line-clamp-2 text-slate-600"
          : "block max-w-[220px] truncate text-slate-600"
      }
      title={text}
    >
      {text}
    </span>
  ) : (
    <span className="text-slate-300">{empty}</span>
  )

  if (!showLabel) {
    return (
      <span className={className} data-testid={testId}>
        {body}
      </span>
    )
  }

  return (
    <div className={className} data-testid={testId}>
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        Last Remarks
      </p>
      <div className="mt-0.5">{body}</div>
    </div>
  )
}
