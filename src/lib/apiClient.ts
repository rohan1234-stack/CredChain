// ---------------------------------------------------------------------------
// Central HTTP client for talking to the FastAPI backend.
//
// This is the ONE place that: knows the API base URL, attaches the JWT
// (via setAuthToken), and turns a non-2xx response into a typed ApiError.
// Nothing else in the app should call fetch() directly against the backend —
// keeps token handling from being scattered across components.
// ---------------------------------------------------------------------------

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

let authToken: string | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

/** status 0 means the request never reached the server (network/CORS failure) — surfaced as "server unavailable". */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function authHeader(): HeadersInit {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {}
}

/**
 * FastAPI's default handler for a Pydantic request-validation failure (422) never sends a plain
 * string `detail` — it's always an array of `{ loc, msg, type }` objects, one per failing field
 * (e.g. our own password-strength check in schemas/auth.py: RegisterRequest._password_strength).
 * Each `msg` is validator-authored, human-readable text — Pydantic v2 just prefixes a custom
 * validator's raised message with "Value error, " — never a stack trace or internal path, so
 * it's safe to show as-is once that prefix is stripped.
 */
function formatValidationErrors(errors: unknown[]): string | null {
  const messages = errors
    .map((e) => (e && typeof e === 'object' && 'msg' in e ? String((e as { msg: unknown }).msg) : null))
    .filter((m): m is string => !!m)
    .map((m) => m.replace(/^Value error,\s*/, '').trim())
    .filter((m) => m.length > 0)
  if (messages.length === 0) return null
  return messages.map((m) => (/[.!?]$/.test(m) ? m : `${m}.`)).join(' ')
}

async function handleErrorAndAuth(response: Response): Promise<void> {
  if (response.status === 401) {
    // Token missing/invalid/expired — clear it and let AuthContext react
    // (redirects to /login) without every caller needing to know about auth.
    setAuthToken(null)
    window.dispatchEvent(new CustomEvent('credchain:unauthorized'))
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (Array.isArray(body?.detail)) {
        detail = formatValidationErrors(body.detail) ?? detail
      }
    } catch {
      // response wasn't JSON — keep the default detail message
    }
    throw new ApiError(response.status, detail)
  }
}

// Bounded client-side timeout so a hung/slow backend (e.g. a cold-starting Render instance)
// can't leave a request — most importantly login — waiting indefinitely. Long enough to ride
// out a real cold start, short enough to eventually surface a clear error instead of a spinner
// that never resolves.
const REQUEST_TIMEOUT_MS = 18_000

async function fetchSafe(path: string, options: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    return await fetch(`${API_BASE_URL}${path}`, { ...options, signal: controller.signal })
  } catch {
    // Covers both a real network/CORS failure and our own timeout abort (fetch rejects with an
    // AbortError in that case) — either way there's no response to work with, so both collapse
    // into the same "server unavailable" ApiError rather than an uncaught AbortError.
    throw new ApiError(0, 'Server unavailable. Check your connection and try again.')
  } finally {
    clearTimeout(timeoutId)
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetchSafe(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...options.headers },
  })
  await handleErrorAndAuth(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** For multipart/form-data (file uploads) — deliberately does NOT set Content-Type, so the browser can add its own boundary. */
async function requestForm<T>(path: string, formData: FormData, method = 'POST'): Promise<T> {
  const response = await fetchSafe(path, { method, body: formData, headers: authHeader() })
  await handleErrorAndAuth(response)
  return (await response.json()) as T
}

/** For downloading a protected binary response (e.g. a credential's document) as a Blob. */
async function requestBlob(path: string): Promise<Blob> {
  const response = await fetchSafe(path, { headers: authHeader() })
  await handleErrorAndAuth(response)
  return response.blob()
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: <T>(path: string, formData: FormData) => requestForm<T>(path, formData),
  getBlob: (path: string) => requestBlob(path),
}
