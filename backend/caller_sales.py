"""Caller daily-sales report column mapping (pure helpers, no DB)."""


def norm_disp_name(name) -> str:
    return (name or "").strip().lower()


def sales_disp_counts(disp_counts: dict) -> dict:
    """Map disposition call counts to daily-sales columns (case-insensitive aliases)."""
    interested = registered = deposite = 0
    for name, count in disp_counts.items():
        n = norm_disp_name(name)
        if n == "interested" or n.startswith("interested /") or n.startswith("interested/"):
            interested += count
        elif n == "registered":
            registered += count
        elif n in ("deposite", "deposit"):
            deposite += count
    return {"interested": interested, "registered": registered, "deposite": deposite}
