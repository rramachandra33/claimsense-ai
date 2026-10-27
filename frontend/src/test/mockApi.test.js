import { describe, expect, it } from 'vitest'
import { assess, FORBIDDEN } from '../mockApi'
import demoTokens from '../data/demo_tokens.json'

const tok = (label) => demoTokens.find((t) => t.label === label).token
const NOW = Date.parse('2026-10-26T12:00:00Z')
const run = (req) => assess({ claimId: 'CLM-2025-3001', userId: 'u-adj-n1', group: 'NORTH', ...req }, NOW)

function expectForbidden(res, reason) {
  expect(res.status).toBe(403)
  expect(res.body).toEqual(FORBIDDEN.body)
  expect(res.audit.granted).toBe(false)
  if (reason) expect(res.audit.reason).toMatch(reason)
}

describe('simulated access check', () => {
  it('EV-097: NORTH adjuster on a NORTH claim is granted', async () => {
    const res = await run({ token: tok('Adjuster NORTH') })
    expect(res.status).toBe(200)
    expect(res.body).toMatchObject({ claim_id: 'CLM-2025-3001', user_id: 'u-adj-n1' })
    expect(res.audit.granted).toBe(true)
  })

  it('EV-098: WEST adjuster on the same claim is refused', async () => {
    expectForbidden(await run({ token: tok('Adjuster WEST'), userId: 'u-adj-w1', group: 'WEST' }), /region NORTH/)
  })

  it('refuses a typed User ID that differs from the token (impersonation)', async () => {
    expectForbidden(await run({ token: tok('Adjuster WEST'), userId: 'u-adj-n1' }), /does not match/)
  })

  it('refuses a typed Group outside the token regions', async () => {
    expectForbidden(await run({ token: tok('Adjuster NORTH'), group: 'WEST' }), /Group/)
  })

  it('refuses no token, expired and tampered tokens', async () => {
    expectForbidden(await run({ token: '' }), /No token/)
    expectForbidden(await run({ token: tok('Expired token') }), /expired/)
    expectForbidden(await run({ token: tok('Tampered token'), userId: 'u-adj-w1' }), /signature/)
    expectForbidden(await run({ token: 'not.a.jwt' }), /signature/)
  })

  it('refuses suspended users, auditors and service accounts', async () => {
    expectForbidden(await run({ token: tok('Suspended adjuster'), userId: 'u-adj-n3' }), /not active/)
    expectForbidden(await run({ token: tok('Auditor'), userId: 'u-aud-1' }), /Role auditor/)
    expectForbidden(await run({ token: tok('Service account'), userId: 'svc-pipeline' }), /Group/)
  })

  it('supervisor is granted across regions', async () => {
    const res = await run({ token: tok('Supervisor'), userId: 'u-sup-1', claimId: 'CLM-2024-3001', group: 'EAST' })
    expect(res.status).toBe(200)
  })

  it('EV-106: unknown claim gets the same body as an unauthorised one', async () => {
    const unknown = await run({ token: tok('Adjuster NORTH'), claimId: 'CLM-9999-0000' })
    const unauthorised = await run({ token: tok('Adjuster WEST'), userId: 'u-adj-w1', group: 'WEST' })
    expectForbidden(unknown, /Unknown claim/)
    expect(unknown.body).toEqual(unauthorised.body)
  })
})
