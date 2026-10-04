/** Error raised by the API client (real or mock). `message` is always Persian and safe to show. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** `error.details` of the backend envelope: for `invalid_record`, the Persian messages, one per problem. */
  readonly details: unknown;

  constructor(code: string, message: string, status = 0, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

/**
 * Error codes the tabs react to (backend/app/api/deps.py, data.py). Others are shown by message.
 *   401: auth_required, invalid_token  |  503: auth_unavailable
 *   404: bot_not_found, run_not_found, revision_not_found, collection_not_found, record_not_found
 *   409: no_active_revision, record_has_active_bookings
 *   400: invalid_record (details: string[])  |  405: read_only_collection
 */
export const ERROR_CODES = {
  noActiveRevision: "no_active_revision",
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
