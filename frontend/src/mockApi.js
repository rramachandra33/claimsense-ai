// Simulated backend for POST /claims/{id}/assess. It stands in for the real server so the
// screen can be tried before any backend exists. The rule mirrors
// data/synthetic/users.json -> access_rule; the real check must live server side.

import claimsOpen from './data/claims_open.json'
import users from './data/users.json'
import access from './data/access.json'
import { decodeJwt, verifyHs256 } from './jwt'

const CAN_ADJUDICATE = new Set(['adjuster', 'senior_adjuster', 'supervisor', 'siu_investigator'])
const usersById = new Map(users.map((u) => [u.user_id, u]))
const claimsById = new Map(claimsOpen.map((c) => [c.claim_id, c]))

// Every refusal returns this exact body: no claim data, no hint whether the claim exists.
export const FORBIDDEN = Object.freeze({ status: 403, body: { error: 'forbidden', message: 'You are not entitled to this claim.' } })

export async function assess({ claimId, userId, group, token }, now = Date.now()) {
  const claim_id = (claimId || '').trim().toUpperCase()
  const typedUser = (userId || '').trim()
  const audit = (granted, reason, user = null) => ({
    at: new Date(now).toISOString(),
    claim_id: claim_id || null,
    token_sub: user,
    typed_user_id: typedUser || null,
    typed_group: group || null,
    granted,
    reason,
  })
  const refuse = (reason, user = null) => ({ ...FORBIDDEN, audit: audit(false, reason, user) })

  if (!token || !token.trim()) return refuse('No token')
  const decoded = decodeJwt(token)
  if (!decoded || !(await verifyHs256(token, access.demo_secret))) return refuse('Invalid token signature')
  const { sub, regions = [], exp } = decoded.payload
  if (typeof exp !== 'number' || exp * 1000 <= now) return refuse('Token expired', sub)

  const user = usersById.get(sub)
  if (!user || user.status !== 'active') return refuse(`User ${sub} not found or not active`, sub)
  if (typedUser !== sub) return refuse(`Typed User ID "${typedUser}" does not match token subject`, sub)
  if (!regions.includes(group)) return refuse(`Typed Group "${group}" is not in the token's regions`, sub)
  if (!CAN_ADJUDICATE.has(user.role)) return refuse(`Role ${user.role} may not request adjudication`, sub)

  const claim = claimsById.get(claim_id)
  if (!claim) return refuse('Unknown claim ID', sub)
  // Entitlement uses the server's user record, not the regions the token claims.
  if (!user.regions.includes(claim.region)) return refuse(`Claim region ${claim.region} not in user's regions`, sub)

  return {
    status: 200,
    body: { claim_id: claim.claim_id, region: claim.region, user_id: user.user_id, role: user.role, simulated: true },
    audit: audit(true, 'Granted', sub),
  }
}
