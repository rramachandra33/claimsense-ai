import { cookies } from "next/headers";

const COOKIE_NAME = "claimsense_session";

/**
 * The signed-in user. The token is the one the ClaimSense data API issued; the console never
 * decides access itself, it only forwards this token. The cookie is httpOnly, so page scripts
 * cannot read it.
 */
export type Session = {
  token: string;
  userId: string;
  fullName: string;
  group: string | null;
};

export function getSession(): Session | null {
  const raw = cookies().get(COOKIE_NAME)?.value;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (typeof parsed.token === "string" && typeof parsed.userId === "string") {
      return {
        token: parsed.token,
        userId: parsed.userId,
        fullName: parsed.fullName ?? parsed.userId,
        group: parsed.group ?? null,
      };
    }
  } catch {
    // fall through
  }
  return null;
}

/**
 * A Secure cookie is only sent over HTTPS (or to localhost). In production it is on, unless
 * CLAIMSENSE_COOKIE_SECURE=0: the EC2 console is still plain HTTP, and there the browser would
 * drop a Secure cookie and every page would go back to the sign-in screen. Turn it back on once
 * the console is behind HTTPS.
 */
function secureCookie(): boolean {
  if (process.env.CLAIMSENSE_COOKIE_SECURE === "0") return false;
  return process.env.NODE_ENV === "production";
}

export function setSession(session: Session): void {
  cookies().set(COOKIE_NAME, JSON.stringify(session), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: secureCookie(),
    maxAge: 60 * 60 * 8, // matches the 8-hour dev token
  });
}

export function clearSession(): void {
  cookies().delete(COOKIE_NAME);
}
