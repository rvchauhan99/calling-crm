/** Mirror of backend sheet_sync META_COLUMN_MAP / GENERIC_COLUMN_MAP */

export const META_COLUMN_MAP = {
  name: "full_name",
  phone: "phone_number",
  email: "email",
  city: "",
  external_id: "id",
}

export const GENERIC_COLUMN_MAP = {
  name: "name",
  phone: "phone",
  email: "email",
  city: "city",
  external_id: "id",
}

export function defaultColumnMap(preset) {
  if (preset === "generic") return { ...GENERIC_COLUMN_MAP }
  return { ...META_COLUMN_MAP }
}

export const COLUMN_MAP_FIELDS = [
  { key: "name", label: "Name", required: true, testId: "sheet-map-name" },
  { key: "phone", label: "Phone", required: true, testId: "sheet-map-phone" },
  { key: "email", label: "Email", required: false, testId: "sheet-map-email" },
  { key: "city", label: "City", required: false, testId: "sheet-map-city" },
  { key: "external_id", label: "External ID", required: false, testId: "sheet-map-external-id" },
]
