import { validatePhone } from "@/lib/leadValidation"

test("validatePhone accepts India and US and rejects a short code", () => {
  expect(validatePhone("9876543210")).toBe("")
  expect(validatePhone("+14155552671")).toBe("")
  expect(validatePhone("p:+918847490594")).toBe("")
  expect(validatePhone("+1")).toBe("Invalid phone number.")
  expect(validatePhone("")).toBe("Phone is required")
})
