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

export function setSession(session: Session): void {
  cookies().set(COOKIE_NAME, JSON.stringify(session), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
    maxAge: 60 * 60 * 8, // matches the 8-hour dev token
  });
}

export function clearSession(): void {
  cookies().delete(COOKIE_NAME);
}
