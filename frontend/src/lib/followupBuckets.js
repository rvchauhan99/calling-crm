/** Shared follow-up / queue bucket helpers for Follow-ups + Today Calls. */

export const dayKey = (d) => {
  const x = new Date(d)
  return `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`
}

export const classifyFollowup = (followUpAt, now = new Date()) => {
  const at = new Date(followUpAt)
  if (Number.isNaN(at.getTime())) return "upcoming"
  if (dayKey(at) === dayKey(now)) return "today"
  if (at < now) return "overdue"
  return "upcoming"
}

const CATEGORY_PRIORITY = { overdue: 0, today: 1, upcoming: 2 }

export const sortFollowups = (items, now = new Date()) => {
  return [...items].sort((a, b) => {
    const ca = classifyFollowup(a.follow_up_at, now)
    const cb = classifyFollowup(b.follow_up_at, now)
    if (CATEGORY_PRIORITY[ca] !== CATEGORY_PRIORITY[cb]) {
      return CATEGORY_PRIORITY[ca] - CATEGORY_PRIORITY[cb]
    }
    return new Date(a.follow_up_at) - new Date(b.follow_up_at)
  })
}

export const followupPillColor = (category) => {
  if (category === "overdue") return "red"
  if (category === "today") return "amber"
  return "sky"
}

export const QUEUE_BUCKETS = [
  { id: "overdue", label: "Overdue", color: "red" },
  { id: "due_today", label: "Due today", color: "amber" },
  { id: "assigned_today", label: "Assigned today", color: "sky" },
  { id: "upcoming", label: "Upcoming", color: "slate" },
]

export const urgencyLabel = (lead) => {
  const reason = lead.queue_reason
  if (reason === "overdue") {
    const d = lead.days_overdue
    return d ? `${d} day${d === 1 ? "" : "s"} overdue` : "Overdue"
  }
  if (reason === "due_today") {
    if (lead.follow_up_at) {
      return `Due today · ${new Date(lead.follow_up_at).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
      })}`
    }
    return "Due today"
  }
  if (reason === "upcoming") {
    if (lead.follow_up_at) {
      const days = Math.max(
        1,
        Math.ceil((new Date(lead.follow_up_at) - new Date()) / (1000 * 60 * 60 * 24)),
      )
      return `In ${days} day${days === 1 ? "" : "s"}`
    }
    return "Upcoming"
  }
  if (reason === "assigned_today") return "Assigned today"
  if (reason === "called_today") return "Called today"
  return null
}

export const toDatetimeLocalValue = (iso) => {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Current local datetime for datetime-local inputs. */
export const nowDatetimeLocalValue = () => toDatetimeLocalValue(new Date().toISOString())

export const isCallBackDisposition = (disp) => disp?.name === "Call Back"

export const isConvertDisposition = (disp) => (
  Boolean(disp?.converts_to_client || disp?.name === "Converted")
)

export const isTerminalStage = (stage) => stage === "Won" || stage === "Lost"

/** Return positive number for API, or null if empty/zero/invalid. */
export const parseDepositAmount = (raw) => {
  if (raw === "" || raw == null) return null
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return null
  return n
}

