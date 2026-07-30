// src/auth/SessionNotice.tsx
//
// The visible half of "a transient failure must not sign anyone out".
//
// Before the classifier landed, a failed `GET /auth/me` ejected the athlete to
// the sign-in gate — brutal, but at least legible. Now the token survives and
// `user` stays null, so the app renders normally with every token-gated card in
// its own `unavailable / load_failed` state (see overviewModel.ts:84). That is
// honest but unexplained: eight cards each say "unavailable" and nothing says
// why, or offers a way back.
//
// This notice is that missing explanation. It is non-blocking (fixed, out of
// the document flow, does not gate any screen), persistent until the session
// resolves or the athlete dismisses it, and it carries the ONE control that can
// actually fix the situation. A retry that fails leaves the notice up and says
// so — it never silently resets, because "the button did nothing" is exactly
// how an athlete concludes the app is broken.
import { useCallback, useState } from "react";

import type { SessionUnavailable } from "./perfLabAuthContext";
import { useAuth } from "./useAuth";

/**
 * Shell-level host. Renders nothing at all while the session is healthy (or
 * absent), so the notice's whole lifecycle is mount → resolve → unmount.
 *
 * Keying on `reason` resets the view's retry/dismiss state when the FAILURE
 * changes underneath it: a dismissed 503 must not swallow a later offline drop.
 */
export function SessionNotice() {
  const { sessionUnavailable, retrySession } = useAuth();
  if (!sessionUnavailable) return null;
  return (
    <SessionNoticeView
      key={sessionUnavailable.reason}
      notice={sessionUnavailable}
      onRetry={retrySession}
    />
  );
}

const RETRY_BUTTON =
  "rounded-[9px] border border-warn/30 bg-warn/[0.12] px-[13px] py-[8px] text-[12.5px] font-semibold leading-none text-warn outline-none focus-visible:ring-2 focus-visible:ring-warn focus-visible:ring-offset-2 focus-visible:ring-offset-panel disabled:opacity-60 motion-reduce:transition-none motion-reduce:hover:transform-none";

const DISMISS_BUTTON =
  "rounded-[8px] border border-white/10 bg-white/[0.03] px-[10px] py-[7px] text-[11.5px] font-medium leading-none text-mute outline-none focus-visible:ring-2 focus-visible:ring-mute focus-visible:ring-offset-2 focus-visible:ring-offset-panel motion-reduce:transition-none motion-reduce:hover:transform-none";

/**
 * Presentational half, exported for direct state-by-state testing.
 *
 * `onRetry` resolves either way — success is signalled by this component being
 * unmounted (the host stops rendering it), so "still mounted after a finished
 * attempt" IS the failure signal. That is why the failed-retry line is derived
 * rather than stored: there is no way for it to disagree with what is on screen.
 */
export function SessionNoticeView({
  notice,
  onRetry,
}: {
  notice: SessionUnavailable;
  onRetry: () => Promise<void>;
}) {
  const [attempts, setAttempts] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const handleRetry = useCallback(async () => {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      // Reached only while still mounted — a successful retry clears
      // `sessionUnavailable`, and the host unmounts this subtree.
      setRetrying(false);
      setAttempts((n) => n + 1);
    }
  }, [onRetry]);

  if (dismissed) return null;

  const retryFailed = attempts > 0 && !retrying;

  return (
    <div
      data-testid="session-notice"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="fixed bottom-4 left-1/2 z-50 w-[min(440px,calc(100vw-2rem))] -translate-x-1/2 rounded-[14px] border border-warn/30 bg-panel p-4 shadow-[0_18px_40px_-22px_rgba(0,0,0,0.85)] motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2"
    >
      <div className="flex items-start gap-3">
        <svg
          aria-hidden="true"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--color-warn)"
          strokeWidth="1.8"
          strokeLinecap="round"
          className="mt-[1px] flex-none"
        >
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
          <path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
        </svg>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold leading-none text-ink">
            Couldn't reach the server
          </div>
          <p className="mt-[7px] text-[12.5px] font-medium leading-[1.5] text-mute">
            {notice.message}
          </p>
          {retryFailed && (
            <p
              data-testid="session-notice-result"
              className="mt-[6px] text-[12px] font-medium leading-[1.5] text-warn"
            >
              Still couldn't reach the server. You are still signed in —
              nothing was lost.
            </p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              data-testid="session-notice-retry"
              onClick={handleRetry}
              disabled={retrying}
              aria-busy={retrying}
              className={RETRY_BUTTON}
            >
              {retrying ? "Checking…" : "Try again"}
            </button>
            <button
              type="button"
              data-testid="session-notice-dismiss"
              onClick={() => setDismissed(true)}
              className={DISMISS_BUTTON}
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
