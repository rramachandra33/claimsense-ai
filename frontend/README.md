# ClaimSense frontend (prototype)

Split-screen adjuster console. Left: Claim ID, User ID, Group, JWT and **Run assessment**.
Right: open claims with the assigned adjuster. Styling follows ClarityFI (DM Sans / Manrope,
green, mint and purple on cream).

**There is no real backend yet.** `src/mockApi.js` simulates `POST /claims/{id}/assess` in the
browser: it verifies the demo JWT (HS256), checks the typed User ID and Group against the token,
and applies `data/synthetic/users.json → access_rule`. Every refusal returns the same 403 body
with no claim data; the reason goes only to the audit entry. Agents are not called.

```bash
cd frontend
npm install
npm run data   # regenerate src/data/*.json from data/synthetic/ (after re-running the generator)
npm run dev    # http://localhost:5173
npm test       # access-check tests (EV-097, EV-098, EV-106, impersonation, bad tokens)
```

Demo-only shortcuts that must not reach the real system:
- the JWT signing secret ships in `src/data/access.json` (the real key stays server side);
- the claims list shows every synthetic claim (the real list must be filtered by the backend to the
  claims the token is entitled to).
