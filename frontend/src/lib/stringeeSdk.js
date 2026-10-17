/**
 * Lazy-load Stringee Web SDK from CDN (or use global if already present).
 * https://cdn.stringee.com/sdk/web/latest/stringee-web-sdk.min.js
 */

const STRINGEE_CDN = "https://cdn.stringee.com/sdk/web/latest/stringee-web-sdk.min.js"

let loadPromise = null

export function loadStringeeSdk() {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Stringee SDK requires a browser"))
  }
  if (window.StringeeClient && window.StringeeCall) {
    return Promise.resolve({
      StringeeClient: window.StringeeClient,
      StringeeCall: window.StringeeCall,
      StringeeUtil: window.StringeeUtil,
    })
  }
  if (loadPromise) return loadPromise
  loadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-stringee-sdk="1"]')
    if (existing) {
      existing.addEventListener("load", () => {
        if (window.StringeeClient) {
          resolve({
            StringeeClient: window.StringeeClient,
            StringeeCall: window.StringeeCall,
            StringeeUtil: window.StringeeUtil,
          })
        } else reject(new Error("Stringee SDK failed to load"))
      })
      return
    }
    const script = document.createElement("script")
    script.src = STRINGEE_CDN
    script.async = true
    script.dataset.stringeeSdk = "1"
    script.onload = () => {
      if (window.StringeeClient && window.StringeeCall) {
        resolve({
          StringeeClient: window.StringeeClient,
          StringeeCall: window.StringeeCall,
          StringeeUtil: window.StringeeUtil,
        })
      } else {
        loadPromise = null
        reject(new Error("Stringee SDK globals missing after load"))
      }
    }
    script.onerror = () => {
      loadPromise = null
      reject(new Error("Failed to load Stringee Web SDK"))
    }
    document.head.appendChild(script)
  })
  return loadPromise
}
