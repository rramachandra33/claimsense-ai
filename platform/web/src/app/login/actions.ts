"use server";

import { redirect } from "next/navigation";
import { devLogin, whoIs } from "@/lib/claimsense";
import { cognitoConfig, cognitoSignIn } from "@/lib/cognito";
import { setSession } from "@/lib/session";

type LoginState = { error: string | null };

export async function loginAction(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const userId = String(formData.get("userId") ?? "").trim();
  if (!userId) {
    return { error: "Enter a user name, for example alice." };
  }

  const cognito = cognitoConfig();
  if (cognito) {
    const password = String(formData.get("password") ?? "");
    if (!password) {
      return { error: "Enter your password." };
    }
    const signIn = await cognitoSignIn(cognito, userId, password);
    if (!signIn.ok) {
      return { error: signIn.message };
    }
    // The data API decides who this is and whether they may use ClaimSense (a suspended user
    // has a working Cognito password but is refused here).
    const user = await whoIs(signIn.accessToken);
    if (!user.ok) {
      if (user.status === 403) {
        return { error: "Your account may not use ClaimSense." };
      }
      return { error: user.error?.message ?? "Sign-in failed." };
    }
    setSession({
      token: signIn.accessToken,
      userId: user.data.user_id,
      fullName: user.data.full_name,
      group: user.data.group,
    });
    redirect("/claims");
  }

  const result = await devLogin(userId);
  if (!result.ok) {
    if (result.status === 404) {
      return { error: "Development sign-in is off. Start the API with CLAIMSENSE_DEV_LOGIN=1." };
    }
    return { error: result.error?.message ?? "Sign-in failed." };
  }

  setSession({
    token: result.data.token,
    userId: result.data.user_id,
    fullName: result.data.full_name,
    group: result.data.group,
  });
  redirect("/claims");
}
