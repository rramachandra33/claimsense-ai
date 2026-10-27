import { getSession } from "./session";
import type { RunResult } from "./types";

/** Base URL of the ClaimSense data API (the Python service in api/). */
const API_URL = process.env.CLAIMSENSE_API_URL ?? "http://localhost:8000";

/** Base URL of the runner service that runs the four agents (agent/, `make runner`). */
const RUNNER_URL = process.env.CLAIMSENSE_RUNNER_URL ?? "http://localhost:8100";

export type ApiError = { code: string; message: string };

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiError };

/**
 * GET a data-API path as the signed-in user. Server-side only: the token stays on the server.
 * Refusals come back as { ok: false }, so pages can show the API's own message.
 */
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const session = getSession();
  try {
    const response = await fetch(`${API_URL}${path}`, {
      headers: session ? { Authorization: `Bearer ${session.token}` } : {},
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) {
      return { ok: false, status: response.status, error: body.error };
    }
    return { ok: true, status: response.status, data: body as T };
  } catch {
    return {
      ok: false,
      status: 503,
      error: { code: "api_unreachable", message: `The ClaimSense API at ${API_URL} is not reachable.` },
    };
  }
}

export type DevLogin = { token: string; user_id: string; full_name: string; group: string | null };

/** Development sign-in (the API only allows it when CLAIMSENSE_DEV_LOGIN=1). */
export async function devLogin(userId: string): Promise<ApiResult<DevLogin>> {
  try {
    const response = await fetch(`${API_URL}/api/v1/dev/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) {
      return { ok: false, status: response.status, error: body.error };
    }
    return { ok: true, status: response.status, data: body as DevLogin };
  } catch {
    return {
      ok: false,
      status: 503,
      error: { code: "api_unreachable", message: `The ClaimSense API at ${API_URL} is not reachable.` },
    };
  }
}

/**
 * Ask the runner to assess one claim as the signed-in user. The runner forwards the user's token
 * to the data API, which decides access; the console decides nothing itself.
 */
export async function runAssessment(claimId: string): Promise<ApiResult<RunResult>> {
  const session = getSession();
  try {
    const response = await fetch(`${RUNNER_URL}/runs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
      },
      body: JSON.stringify({ claim_id: claimId }),
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) {
      return { ok: false, status: response.status, error: body.error };
    }
    return { ok: true, status: response.status, data: body as RunResult };
  } catch {
    return {
      ok: false,
      status: 503,
      error: { code: "runner_unreachable", message: `The ClaimSense runner at ${RUNNER_URL} is not reachable. Start it with: make runner` },
    };
  }
}
