/**
 * Dead-connection detector for the run event stream. The server writes something at least every 15 s (an
 * event or a `: heartbeat` comment), so a connection that delivers no bytes at all for `STALL_MS` is dead
 * even though the socket still looks open. Pure: no DOM, no fetch.
 */

/** No bytes for this long means the connection is dead (more than two missed 15 s heartbeats). */
export const STALL_MS = 35_000;

export interface Watchdog {
  /** Any bytes arrived: restart the countdown. */
  poke(): void;
  /** Stop for good (the connection ended or was aborted). */
  stop(): void;
}

/** Calls `onStall` once if `poke` is not called within `timeoutMs`. Starts counting immediately. */
export function createWatchdog(onStall: () => void, timeoutMs: number = STALL_MS): Watchdog {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  const arm = () => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (!stopped) {
        stopped = true;
        onStall();
      }
    }, timeoutMs);
  };
  arm();
  return {
    poke() {
      if (!stopped) arm();
    },
    stop() {
      stopped = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}
