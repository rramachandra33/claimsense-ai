"use client";

import { useFormState, useFormStatus } from "react-dom";
import { loginAction } from "./actions";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-lg bg-claimsense-primary px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-claimsense-deep disabled:opacity-60"
    >
      {pending ? "Signing in…" : "Sign in"}
    </button>
  );
}

/** cognito: ask for a password too (Amazon Cognito sign-in); otherwise the development sign-in. */
export function LoginForm({ cognito }: { cognito: boolean }) {
  const [state, formAction] = useFormState(loginAction, { error: null });
  return (
    <form action={formAction} className="space-y-4">
      <div>
        <label htmlFor="userId" className="block text-sm font-medium text-slate-700">
          {cognito ? "User name" : "User id"}
        </label>
        <input
          id="userId"
          name="userId"
          type="text"
          autoComplete="username"
          defaultValue={cognito ? "" : "alice"}
          className="mt-1 w-full rounded-lg border border-claimsense-line px-3 py-2 font-mono text-sm shadow-sm focus:border-claimsense-primary focus:outline-none focus:ring-1 focus:ring-claimsense-primary"
        />
      </div>
      {cognito ? (
        <div>
          <label htmlFor="password" className="block text-sm font-medium text-slate-700">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            className="mt-1 w-full rounded-lg border border-claimsense-line px-3 py-2 text-sm shadow-sm focus:border-claimsense-primary focus:outline-none focus:ring-1 focus:ring-claimsense-primary"
          />
        </div>
      ) : null}
      {state.error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
          {state.error}
        </p>
      ) : null}
      <SubmitButton />
    </form>
  );
}
