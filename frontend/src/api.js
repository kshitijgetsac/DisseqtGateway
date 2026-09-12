const base = '/api/v1'

export async function api(path, { method = 'GET', body, userId, headers = {} } = {}) {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(userId ? { 'X-Demo-User-Id': userId } : {}),
      ...headers,
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    const error = new Error(data?.error?.message || `Request failed (${response.status})`)
    error.code = data?.error?.code || `HTTP_${response.status}`
    error.status = response.status
    error.details = data?.error
    throw error
  }
  return data
}

export function query(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
