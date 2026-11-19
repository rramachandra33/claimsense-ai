# DECISIONS.md

Engagement decision log (ADR-lite). Newest first.

## 2026-10-07 - Scope the pilot to Type-A (fraud) disputes first
- **Decision:** Scope the pilot to Type-A (fraud) disputes first
- **Why:** Type-A has the cleaner Reg E clock and the clearest auto-triage signal; it lets us prove value before touching the messier Type-B merchant cases.
- **Alternatives considered:** Do both types at once (rejected - doubles the eval surface and the RBAC complexity before we have proven anything).
- **Owner:** Forgepoint FDE team
- **Revisit when:** After M2 hits >=80% auto-triage on Type-A

## 2026-10-07 - W13 is discovery only - no build until success criteria are agreed
- **Decision:** W13 is discovery only - no build until success criteria are agreed
- **Why:** Nobody at Meridian can define success yet. Building now means building the wrong thing fast and burning trust with a hostile ops head.
- **Alternatives considered:** Start a prototype to show momentum (rejected - momentum toward an undefined target is just risk we will pay for in week five).
- **Owner:** Forgepoint FDE team
- **Revisit when:** After M0 charter sign-off
