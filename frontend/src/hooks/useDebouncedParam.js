import { useEffect, useState } from "react"

/** Local input state that syncs to a URL/search callback after `delay` ms. */
export const useDebouncedParam = (urlValue, onCommit, delay = 300) => {
  const [local, setLocal] = useState(urlValue || "")

  useEffect(() => {
    setLocal(urlValue || "")
  }, [urlValue])

  useEffect(() => {
    const t = setTimeout(() => {
      if ((local || "") !== (urlValue || "")) onCommit(local)
    }, delay)
    return () => clearTimeout(t)
  }, [local, urlValue, onCommit, delay])

  return [local, setLocal]
}
