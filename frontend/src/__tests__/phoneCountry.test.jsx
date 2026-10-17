import { validatePhone } from "@/lib/leadValidation"
import { formatPhoneDisplay } from "@/lib/phoneDisplay"

test("validatePhone accepts India and US and rejects a short code", () => {
  expect(validatePhone("9876543210")).toBe("")
  expect(validatePhone("+14155552671")).toBe("")
  expect(validatePhone("p:+918847490594")).toBe("")
  expect(validatePhone("+1")).toBe("Invalid phone number.")
  expect(validatePhone("")).toBe("Phone is required")
})

test("formatPhoneDisplay spaces the calling code and leaves junk unchanged", () => {
  expect(formatPhoneDisplay("+18208512485")).toBe("+1 8208512485")
  expect(formatPhoneDisplay("+918603106064")).toBe("+91 8603106064")
  expect(formatPhoneDisplay("not-a-phone")).toBe("not-a-phone")
  expect(formatPhoneDisplay("")).toBe("")
})
