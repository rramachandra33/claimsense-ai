"use server";

import { redirect } from "next/navigation";
import { devLogin } from "@/lib/claimsense";
import { setSession } from "@/lib/session";

export async function loginAction(
  _prevState: { error: string | null },
  formData: FormData
): Promise<{ error: string | null }> {
  const userId = String(formData.get("userId") ?? "").trim();
  if (!userId) {
    return { error: "Enter a user id, for example alice." };
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
