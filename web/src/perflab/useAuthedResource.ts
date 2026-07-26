// src/perflab/useAuthedResource.ts
//
// Data-fetching hook for screens that pull live data from the token-gated
// backend. It owns *authentication and acquisition* state only — see
// `resource.ts` for the contract it returns:
//
//   guest      no token, so no request authority at all (never a request)
//   loading    a token exists and there is no usable payload yet
//   error      the request failed and nothing usable is on screen
//   success    a usable payload, plus a nested refresh attempt state
//
// "Empty" is deliberately NOT a state here: whether zero rows means "you have
// logged nothing yet" is an editorial reading of successful data, decided at the
// renderer via an `isEmpty` predicate (see ResourceState / selectResourceBranch).
//
// A 401 inside the fetcher already clears the session via perfLabClient's
// sessionOn401 path.
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/auth/useAuth";
import {
  initialResource,
  reduceResource,
  toResourceError,
  type AuthedResource,
} from "./resource";

export type { AuthedResource } from "./resource";

export function useAuthedResource<T>(
  fetcher: (token: string) => Promise<T>,
  deps: unknown[] = [],
): AuthedResource<T> {
  const { token } = useAuth();
  const [state, setState] = useState<AuthedResource<T>>(() => initialResource(token != null));

  // Identity is adjusted during render, not in an effect: a token that arrives
  // must read as `loading` on the very first commit (the old hook first-rendered
  // with loading:false, which is what forced every screen's
  // `loading || data === null` dance and flashed empty states for one frame).
  // A replaced token discards the previous user's payload in the same commit —
  // an effect would leave one frame of the wrong athlete's data on screen.
  const [identity, setIdentity] = useState(token);
  if (identity !== token) {
    setIdentity(token);
    setState(initialResource(token != null));
  }

  // Keep the latest fetcher without making it a dep — `deps` drives re-fetch.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!token) {
      setState((s) => (s.status === "guest" ? s : { status: "guest" }));
      return;
    }

    // Request authority: React runs this effect's cleanup before the next effect
    // (token replaced, deps changed) and on unmount, so `cancelled` is what stops
    // an obsolete or slower response from overwriting a newer state. A second
    // generation counter would be redundant — and untestable, since no behavior
    // distinguishes it from this flag.
    let cancelled = false;
    const live = () => !cancelled;

    // Same identity + existing payload => refresh (data stays on screen).
    // Otherwise this is a first load and the resource is already `loading`.
    setState((s) => reduceResource(s, { type: "request-started" }));

    fetcherRef.current(token).then(
      (data) => {
        if (live()) setState((s) => reduceResource(s, { type: "request-succeeded", data }));
      },
      (e: unknown) => {
        if (live()) setState((s) => reduceResource(s, { type: "request-failed", error: toResourceError(e) }));
      },
    );

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, ...deps]);

  return state;
}

// ---------------------------------------------------------------------------
// MIGRATION SHIM — delete before the web PR opens.
//
// The B3 sweep migrates all 25 call sites to `useAuthedResource`; until a given
// file is converted it uses this adapter so every intermediate commit still
// type-checks and builds. `tests/resource-migration.test.ts` fails once the last
// caller is gone, which is the signal to delete this block.
//
// Note it is already strictly honester than the hook it replaces: a failed
// refresh keeps the previous payload instead of nulling it, so a legacy caller
// can no longer fall through `?? sim` on a refresh failure.
// ---------------------------------------------------------------------------

/** @deprecated Legacy `{data, loading, error}` shape. Migrate to AuthedResource. */
export interface Resource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/** @deprecated Migration adapter — see the note above. */
export function toLegacyResource<T>(resource: AuthedResource<T>): Resource<T> {
  switch (resource.status) {
    case "guest":
      return { data: null, loading: false, error: null };
    case "loading":
      return { data: null, loading: true, error: null };
    case "error":
      return { data: null, loading: false, error: resource.error.message };
    case "success":
      return {
        data: resource.data,
        loading: resource.refresh.status === "loading",
        error: resource.refresh.status === "error" ? resource.refresh.error.message : null,
      };
  }
}

/** @deprecated Drop-in for unmigrated call sites. Use `useAuthedResource`. */
export function useLegacyAuthedResource<T>(
  fetcher: (token: string) => Promise<T>,
  deps: unknown[] = [],
): Resource<T> {
  return toLegacyResource(useAuthedResource(fetcher, deps));
}
