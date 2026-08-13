/**
 * Deciding what a failed session check MEANS.
 *
 * `GET /auth/me` failing is not the same thing as "this athlete is logged out".
 * A 401 says the token is no longer accepted; a 503, a CORS error, a dropped
 * Wi-Fi connection or a garbled payload say only that the *backend* could not
 * answer right now. Treating the second group as the first is what signs every
 * open tab out during a deploy or a container restart.
 *
 * The rule this module encodes: ONLY a positively-identified 401 signs the
 * athlete out. Everything else — including anything whose shape we do not
 * recognise — preserves the stored session and surfaces a retryable
 * "we couldn't reach the server" state.
 *
 * Deliberately pure: no DOM, no React, no imports. It is the one place the
 * policy lives, and it is unit-testable on its own.
 */

/** Why the session could not be confirmed, in terms a person would recognise. */
export type SessionUnavailableReason =
  /** The server answered, but with a 5xx — it is up but unhealthy (deploy, restart, crash). */
  | "server-error"
  /** The server answered with a non-401 4xx (403, 404, 429…) — refused, but not "logged out". */
  | "request-rejected"
  /** No HTTP response at all: offline, DNS, CORS, timeout — `fetch` rejects with a `TypeError`. */
  | "network"
  /** The call resolved, but the body was not a session we can use. */
  | "malformed-response"
  /** Something we cannot classify. Preserved on purpose — unknown is never proof of logout. */
  | "unknown";

/**
 * The decision. `action` is the discriminant: `"sign-out"` is reachable ONLY
 * from a 401; every other input lands on `"keep-session"`.
 */
export type AuthFailure =
  | { action: "sign-out"; reason: "session-expired"; status: 401 }
  | {
      action: "keep-session";
      reason: SessionUnavailableReason;
      /** The HTTP status when there was one, `null` when the request never got a response. */
      status: number | null;
    };

/** The `{ message, status, details }` object `perfLabClient` throws (see src/types.ts). */
function readStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const status = (error as { status?: unknown }).status;
  // A non-numeric `status` (string, null, object…) is not a status we can act
  // on — fall through to the preserve-by-default path rather than coercing it.
  return typeof status === "number" && Number.isFinite(status) ? status : null;
}

/**
 * Classify anything thrown by a session check.
 *
 * Accepts `unknown` on purpose: the thrown value may be the client's plain
 * `ApiError` object (which is NOT an `Error` subclass, so `instanceof` is
 * useless), a raw `TypeError` from `fetch`, or literally anything else.
 */
export function classifyAuthFailure(error: unknown): AuthFailure {
  const status = readStatus(error);

  if (status === 401) {
    return { action: "sign-out", reason: "session-expired", status: 401 };
  }

  if (status !== null) {
    return {
      action: "keep-session",
      reason: status >= 500 ? "server-error" : "request-rejected",
      status,
    };
  }

  // No usable status. `fetch` rejects with a TypeError for offline/DNS/CORS
  // failures, so that one case can be named; anything else stays "unknown".
  if (error instanceof TypeError) {
    return { action: "keep-session", reason: "network", status: null };
  }

  return { action: "keep-session", reason: "unknown", status: null };
}

/** The preserve-the-session half of {@link AuthFailure}. */
export type SessionPreserved = Extract<AuthFailure, { action: "keep-session" }>;

/** The decision for a call that RESOLVED but did not return a usable session. */
export const MALFORMED_SESSION_RESPONSE: SessionPreserved = {
  action: "keep-session",
  reason: "malformed-response",
  status: null,
};

/**
 * Does this payload actually describe the signed-in athlete? Guards the one
 * case a `catch` can never see: a 200 carrying an HTML error page, a proxy
 * interstitial, or `null`.
 */
export function isSessionUser(
  payload: unknown,
): payload is { id: number; email: string } {
  if (typeof payload !== "object" || payload === null) return false;
  const { id, email } = payload as { id?: unknown; email?: unknown };
  return typeof id === "number" && typeof email === "string";
}

/** Copy for the retryable banner — plain language, no status codes shouted at the athlete. */
export function describeSessionUnavailable(
  reason: SessionUnavailableReason,
): string {
  switch (reason) {
    case "server-error":
      return "The server is temporarily unavailable. Your session is still signed in.";
    case "request-rejected":
      return "The server refused the session check. Your session is still signed in.";
    case "network":
      return "Couldn't reach the server. Check your connection and try again.";
    case "malformed-response":
      return "The server sent an unexpected response. Your session is still signed in.";
    case "unknown":
      return "Couldn't confirm your session right now. Your session is still signed in.";
  }
}
