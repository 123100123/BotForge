/**
 * Telegram connection errors the backend marks with a stable prefix in `TelegramStatus.last_error`
 * (backend/app/integrations/telegram/texts.py). The poller parks a bot when another server polls the same
 * Telegram bot; the owner retries from Settings › Telegram.
 */
export const POLLING_CONFLICT_PREFIX = "POLLING_CONFLICT:";

/** True when `lastError` is the "another server polls this bot" park. */
export function isPollingConflict(lastError: string | null | undefined): boolean {
  return typeof lastError === "string" && lastError.startsWith(POLLING_CONFLICT_PREFIX);
}

/** The Persian message of a polling-conflict error (the prefix is a marker, not text to show). */
export function pollingConflictMessage(lastError: string): string {
  return lastError.slice(POLLING_CONFLICT_PREFIX.length).trim();
}
