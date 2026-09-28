export function inactiveMasterLabel(name, active) {
  if (!name) return ""
  return active === false ? `${name} (inactive)` : name
}

export function dispositionFilterOptions(dispositions = []) {
  return dispositions
    .filter((d) => d?.name)
    .map((d) => ({
      value: d.name,
      label: inactiveMasterLabel(d.name, d.active),
    }))
}

export function agentFilterOptions(agents = []) {
  return agents
    .filter((a) => a?.id)
    .map((a) => ({
      value: a.id,
      label: inactiveMasterLabel(a.name || a.id, a.active),
    }))
}
