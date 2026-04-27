const BASE_URL = 'http://localhost:8000/api/v1'

export const apiClient = (token) => ({
  get: async (path) => {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Authorization': `Token ${token}` }
    })
    if (!res.ok) throw await res.json()
    return res.json()
  },

  post: async (path, body, idempotencyKey) => {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        'Authorization': `Token ${token}`,
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(body)
    })
    const data = await res.json()
    if (!res.ok) throw data
    return data
  }
})