/** Error raised by the API client (real or mock). `message` is always Persian and safe to show. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** `error.details` of the backend envelope: for `invalid_record`, the Persian messages, one per problem. */
  readonly details: unknown;
  /** `invalid_record`: one message per problem with the FieldDef key it belongs to (null = not tied to a field). */
  readonly fieldErrors: { field: string | null; message: string }[] | null;

  constructor(
    code: string,
    message: string,
    status = 0,
    details?: unknown,
    fieldErrors?: { field: string | null; message: string }[] | null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.fieldErrors = fieldErrors ?? null;
  }
}

/** Reads `field_errors` from an error body; accepted at `error.field_errors` or inside an object `error.details`. */
export function parseFieldErrors(error: { details?: unknown; field_errors?: unknown }): ApiError["fieldErrors"] {
  const raw =
    error.field_errors ??
    (typeof error.details === "object" && error.details !== null && !Array.isArray(error.details)
      ? (error.details as { field_errors?: unknown }).field_errors
      : undefined);
  if (!Array.isArray(raw)) return null;
  const out: { field: string | null; message: string }[] = [];
  for (const item of raw) {
    if (typeof item === "object" && item !== null && typeof (item as { message?: unknown }).message === "string") {
      const field = (item as { field?: unknown }).field;
      out.push({ field: typeof field === "string" ? field : null, message: (item as { message: string }).message });
    }
  }
  return out;
}

/**
 * Error codes the tabs react to (backend/app/api/deps.py, data.py). Others are shown by message.
 *   401: auth_required, invalid_token  |  503: auth_unavailable
 *   404: bot_not_found, run_not_found, revision_not_found, collection_not_found, record_not_found
 *   409: no_active_revision, revision_not_simulatable, record_has_active_bookings
 *   400: invalid_record (details: string[])  |  405: read_only_collection
 */
export const ERROR_CODES = {
  noActiveRevision: "no_active_revision",
  revisionNotSimulatable: "revision_not_simulatable",
  invalidRecord: "invalid_record",
  recordHasActiveBookings: "record_has_active_bookings",
  readOnlyCollection: "read_only_collection",
} as const;

/** Persian text for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return "خطای ناشناخته‌ای رخ داد.";
}
