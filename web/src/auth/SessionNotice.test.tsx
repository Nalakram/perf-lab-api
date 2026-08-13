// @vitest-environment jsdom
//
// The shell's behaviour while a session cannot be confirmed.
//
// AuthContext.test.tsx proves the token SURVIVES a transient failure. This file
// proves the athlete is told about it and can get out of it — because a
// preserved session that renders eight silently-unavailable cards and no
// explanation is only marginally better than being kicked to the sign-in gate.
//
// Everything below drives the REAL <AuthProvider> and the REAL <SessionNotice>
// (the component App mounts), with only the HTTP client mocked — so the states
// under test are produced by the actual classifier, not by hand-set props.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { AuthProvider } from "./AuthContext";
import { SessionNotice } from "./SessionNotice";
import { useAuth } from "./useAuth";

const fetchMe = vi.fn();
const getProfile = vi.fn();

vi.mock("@/api/perfLabClient", () => ({
  fetchMe: (...args: unknown[]) => fetchMe(...args),
  getProfile: (...args: unknown[]) => getProfile(...args),
  login: vi.fn(),
  register: vi.fn(),
  onboard: vi.fn(),
}));

// App's screen tree is irrelevant here and expensive to mount; stub the three
// destinations so what remains under test is App's own gate + notice wiring.
// (These are module mocks — no file in perflab/ is modified.)
vi.mock("@/perflab/store", () => ({
  usePerfLab: () => ({
    state: { screen: "overview" },
    actions: { setScreen: vi.fn() },
  }),
}));
vi.mock("@/perflab/AppShell", () => ({
  AppShell: () => <div data-testid="app-shell" />,
}));
vi.mock("@/perflab/screens/LoginScreen", () => ({
  LoginScreen: () => <div data-testid="login-screen" />,
}));
vi.mock("@/perflab/screens/OnboardingScreen", () => ({
  OnboardingScreen: () => <div data-testid="onboarding-screen" />,
}));

const TOKEN_KEY = "perf_lab_access_token";
const EMAIL_KEY = "perf_lab_session_email";
const TOKEN = "stored-token";
const SESSION_USER = { id: 7, email: "athlete@example.com", is_active: true };

/** The exact object shape perfLabClient throws (src/api/perfLabClient.ts:116-121). */
function apiError(status: number) {
  return { message: `HTTP ${status}`, status, details: undefined };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Stands in for every token-gated surface: does real athlete data reach the screen? */
function AthleteName() {
  const { user } = useAuth();
  return <span data-testid="athlete">{user?.email ?? "(no athlete data)"}</span>;
}

function renderShell() {
  sessionStorage.setItem(TOKEN_KEY, TOKEN);
  sessionStorage.setItem(EMAIL_KEY, "athlete@example.com");
  return render(
    <AuthProvider>
      <AthleteName />
      <SessionNotice />
    </AuthProvider>,
  );
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const notice = () => screen.queryByTestId("session-notice");
const retryButton = () => screen.getByTestId("session-notice-retry");

beforeEach(() => {
  sessionStorage.clear();
  fetchMe.mockReset();
  getProfile.mockReset();
  getProfile.mockResolvedValue(null);
});

afterEach(cleanup);

describe("the notice appears exactly when the session cannot be confirmed", () => {
  it("explains a 503 in the athlete's own words and offers a retry", async () => {
    fetchMe.mockRejectedValue(apiError(503));
    renderShell();
    await settle();

    expect(notice()).not.toBeNull();
    // The copy is the one already defined in describeSessionUnavailable — the
    // notice must not invent a second, drifting vocabulary for the same state.
    expect(notice()!.textContent).toContain("The server is temporarily unavailable");
    expect(notice()!.textContent).toContain("still signed in");
    expect(retryButton().textContent).toBe("Try again");
  });

  it("names the failure differently when the network is the problem", async () => {
    fetchMe.mockRejectedValue(new TypeError("Failed to fetch"));
    renderShell();
    await settle();

    expect(notice()!.textContent).toContain("Couldn't reach the server");
  });

  it("stays away while the session is healthy", async () => {
    fetchMe.mockResolvedValue(SESSION_USER);
    renderShell();
    await settle();

    expect(notice()).toBeNull();
    expect(screen.getByTestId("athlete").textContent).toBe("athlete@example.com");
  });

  it("stays away on a 401 — that athlete really was signed out", async () => {
    fetchMe.mockRejectedValue(apiError(401));
    renderShell();
    await settle();

    expect(notice()).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});

describe("the retry control", () => {
  it("clears the notice and brings the athlete's data back when it succeeds", async () => {
    fetchMe.mockRejectedValueOnce(apiError(503)).mockResolvedValue(SESSION_USER);
    renderShell();
    await settle();
    expect(notice()).not.toBeNull();
    expect(screen.getByTestId("athlete").textContent).toBe("(no athlete data)");

    await act(async () => {
      fireEvent.click(retryButton());
    });

    expect(fetchMe).toHaveBeenCalledTimes(2);
    expect(notice()).toBeNull();
    expect(screen.getByTestId("athlete").textContent).toBe("athlete@example.com");
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
  });

  it("keeps the notice up AND reports the outcome when it fails again", async () => {
    fetchMe.mockRejectedValue(apiError(503));
    renderShell();
    await settle();
    expect(screen.queryByTestId("session-notice-result")).toBeNull();

    await act(async () => {
      fireEvent.click(retryButton());
    });

    // Not a silent reset: the notice is still up and says what just happened.
    expect(notice()).not.toBeNull();
    const result = screen.getByTestId("session-notice-result");
    expect(result.textContent).toContain("Still couldn't reach the server");
    expect(fetchMe).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
  });

  it("says it is working while the retry is in flight, and cannot be double-fired", async () => {
    fetchMe.mockRejectedValueOnce(apiError(503));
    renderShell();
    await settle();

    const pending = deferred<typeof SESSION_USER>();
    fetchMe.mockReturnValueOnce(pending.promise);
    await act(async () => {
      fireEvent.click(retryButton());
    });

    expect(retryButton().textContent).toBe("Checking…");
    expect((retryButton() as HTMLButtonElement).disabled).toBe(true);
    expect(retryButton().getAttribute("aria-busy")).toBe("true");

    fireEvent.click(retryButton());
    expect(fetchMe).toHaveBeenCalledTimes(2);

    await act(async () => {
      pending.resolve(SESSION_USER);
    });
    expect(notice()).toBeNull();
  });
});

describe("dismissal", () => {
  it("hides the notice without disturbing the session", async () => {
    fetchMe.mockRejectedValue(apiError(503));
    renderShell();
    await settle();

    await act(async () => {
      fireEvent.click(screen.getByTestId("session-notice-dismiss"));
    });

    expect(notice()).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
    expect(sessionStorage.getItem(EMAIL_KEY)).toBe("athlete@example.com");
  });
});

describe("accessibility", () => {
  beforeEach(async () => {
    fetchMe.mockRejectedValue(apiError(503));
    renderShell();
    await settle();
  });

  it("is announced politely rather than stealing focus", () => {
    expect(notice()!.getAttribute("role")).toBe("status");
    expect(notice()!.getAttribute("aria-live")).toBe("polite");
    expect(document.activeElement).toBe(document.body);
  });

  it("puts both controls in the keyboard tab order with a visible focus style", () => {
    for (const id of ["session-notice-retry", "session-notice-dismiss"]) {
      const control = screen.getByTestId(id);
      expect(control.tagName).toBe("BUTTON");
      // A real <button> with no negative tabindex is reachable by Tab.
      expect(control.getAttribute("tabindex")).toBeNull();
      control.focus();
      expect(document.activeElement).toBe(control);
      expect(control.className).toContain("focus-visible:ring-2");
    }
  });

  it("does not animate for athletes who asked for reduced motion", () => {
    // Entry animation is motion-safe only; the buttons' inherited hover
    // transform (index.css `button:hover`) is cancelled under motion-reduce.
    expect(notice()!.className).toContain("motion-safe:animate-in");
    expect(notice()!.className).not.toMatch(/(^|\s)animate-in/);
    for (const id of ["session-notice-retry", "session-notice-dismiss"]) {
      expect(screen.getByTestId(id).className).toContain("motion-reduce:transition-none");
    }
  });
});

describe("App mounts the notice — the wiring, not a re-implementation", () => {
  it("renders it over the shell when the session cannot be confirmed", async () => {
    fetchMe.mockRejectedValue(apiError(503));
    sessionStorage.setItem(TOKEN_KEY, TOKEN);
    render(
      <AuthProvider>
        <App />
      </AuthProvider>,
    );
    await settle();

    expect(screen.getByTestId("app-shell")).not.toBeNull();
    expect(notice()).not.toBeNull();
  });

  it("renders nothing extra over a healthy shell", async () => {
    fetchMe.mockResolvedValue(SESSION_USER);
    sessionStorage.setItem(TOKEN_KEY, TOKEN);
    render(
      <AuthProvider>
        <App />
      </AuthProvider>,
    );
    await settle();

    expect(screen.getByTestId("app-shell")).not.toBeNull();
    expect(notice()).toBeNull();
  });

  it("does not reach the shell at all when there is no session", async () => {
    render(
      <AuthProvider>
        <App />
      </AuthProvider>,
    );
    await settle();

    expect(screen.getByTestId("login-screen")).not.toBeNull();
    expect(notice()).toBeNull();
  });
});
