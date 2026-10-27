// Minimal HS256 JWT handling for the simulated backend. Uses Web Crypto, so it runs
// in the browser and in Node (vitest) without a library.

const enc = new TextEncoder()

function b64urlToBytes(s) {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)
  const bin = atob(b64)
  return Uint8Array.from(bin, (ch) => ch.charCodeAt(0))
}

// Returns the payload object, or null if the token is not three well-formed JSON parts.
export function decodeJwt(token) {
  const parts = (token || '').trim().split('.')
  if (parts.length !== 3) return null
  try {
    const header = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[0])))
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[1])))
    return header && payload && typeof payload === 'object' ? { header, payload } : null
  } catch {
    return null
  }
}

export async function verifyHs256(token, secret) {
  const parts = (token || '').trim().split('.')
  const decoded = decodeJwt(token)
  if (!decoded || decoded.header.alg !== 'HS256') return false
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify'])
  try {
    return await crypto.subtle.verify('HMAC', key, b64urlToBytes(parts[2]), enc.encode(`${parts[0]}.${parts[1]}`))
  } catch {
    return false
  }
}
