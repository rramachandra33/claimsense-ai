import { redirect } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { LoginForm } from "./LoginForm";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

// The users in data/identity/users.json (development sign-in only).
const USERS = [
  { id: "alice", role: "Adjuster" },
  { id: "david", role: "Adjuster" },
  { id: "bob", role: "Senior adjuster" },
  { id: "carol", role: "Fraud investigator" },
  { id: "eve", role: "Total-loss appraiser" },
  { id: "frank", role: "Suspended (test)" },
];

export default function LoginPage() {
  if (getSession()) {
    redirect("/claims");
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden flex-col justify-between bg-claimsense-darkest p-12 text-teal-50 lg:flex">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-claimsense-gold font-serif text-lg font-bold text-[#0B2E2A]">
            C
          </span>
          <div className="font-serif text-xl font-semibold tracking-tight text-white">ClaimSense</div>
        </div>
        <div>
          <h2 className="font-serif text-3xl font-semibold leading-tight text-white">
            A first decision in minutes,
            <br />
            with the evidence attached.
          </h2>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-teal-100/70">
            AutoSure claims: read the file, check cover against the policy manual, and review a
            cited draft decision. A licensed adjuster confirms every outcome.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-teal-300/60">
          <ShieldCheck className="h-4 w-4" />
          Synthetic data only · every request is access-checked and audited
        </div>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-claimsense-bg px-6 py-12">
        <div className="w-full max-w-sm">
          <h1 className="text-lg font-semibold text-claimsense-ink">Sign in to ClaimSense</h1>
          <p className="mb-6 mt-1 text-sm text-claimsense-muted">
            Development sign-in: enter a user id. Amazon Cognito replaces this in deployment.
          </p>

          <div className="rounded-xl border border-claimsense-line bg-white p-6 shadow-card">
            <LoginForm />
          </div>

          <div className="mt-4 rounded-lg border border-claimsense-line bg-white/70 p-4 text-xs text-claimsense-muted">
            <div className="mb-2 font-semibold text-claimsense-ink">Users</div>
            <ul className="space-y-1">
              {USERS.map((u) => (
                <li key={u.id} className="flex justify-between gap-3">
                  <span className="font-mono text-claimsense-ink">{u.id}</span>
                  <span className="text-slate-400">{u.role}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
