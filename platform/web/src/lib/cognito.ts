/**
 * Amazon Cognito sign-in for the console (decided 2026-11-05).
 *
 * The sign-in page posts the user name and password to the console's own server, which checks
 * them with Cognito (InitiateAuth, USER_PASSWORD_AUTH) and keeps only the access token, in the
 * httpOnly session cookie. The password never reaches the browser's scripts or the data API.
 * The app client has no secret and the call needs no AWS credentials: it is Cognito's public
 * sign-in endpoint.
 *
 * On when CLAIMSENSE_COGNITO_POOL_ID and CLAIMSENSE_COGNITO_CLIENT_ID are set; otherwise the
 * console uses the development sign-in.
 */

export type CognitoConfig = { region: string; clientId: string };

export function cognitoConfig(): CognitoConfig | null {
  const poolId = process.env.CLAIMSENSE_COGNITO_POOL_ID;
  const clientId = process.env.CLAIMSENSE_COGNITO_CLIENT_ID;
  if (!poolId || !clientId) return null;
  return { region: poolId.split("_")[0], clientId };
}

export type CognitoSignIn = { ok: true; accessToken: string } | { ok: false; message: string };

export async function cognitoSignIn(
  config: CognitoConfig,
  username: string,
  password: string
): Promise<CognitoSignIn> {
  let response: Response;
  try {
    response = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
      },
      body: JSON.stringify({
        AuthFlow: "USER_PASSWORD_AUTH",
        ClientId: config.clientId,
        AuthParameters: { USERNAME: username, PASSWORD: password },
      }),
      cache: "no-store",
    });
  } catch {
    return { ok: false, message: "Amazon Cognito is not reachable. Try again in a minute." };
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const type = String(body.__type ?? "");
    if (type.endsWith("NotAuthorizedException") || type.endsWith("UserNotFoundException")) {
      return { ok: false, message: "Wrong user name or password." };
    }
    if (type.endsWith("PasswordResetRequiredException")) {
      return { ok: false, message: "Your password must be reset. Ask an administrator." };
    }
    if (type.endsWith("TooManyRequestsException")) {
      return { ok: false, message: "Too many attempts. Try again in a minute." };
    }
    return { ok: false, message: "Sign-in failed." };
  }
  if (body.ChallengeName) {
    // The setup script sets permanent passwords, so no challenge is expected.
    return { ok: false, message: "This account needs a new password. Ask an administrator." };
  }
  const accessToken = body.AuthenticationResult?.AccessToken;
  if (typeof accessToken !== "string") {
    return { ok: false, message: "Sign-in failed." };
  }
  return { ok: true, accessToken };
}
