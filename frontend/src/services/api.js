import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,      // send Django session cookie on every request
  headers: { 'Content-Type': 'application/json' },
})

// Attach Django CSRF token to every mutating request
api.interceptors.request.use((config) => {
  if (['post', 'put', 'patch', 'delete'].includes(config.method)) {
    const token = document.cookie
      .split('; ')
      .find((c) => c.startsWith('csrftoken='))
      ?.split('=')[1]
    if (token) config.headers['X-CSRFToken'] = token
  }
  return config
})

// On 401 let ProtectedRoute handle the redirect to /login.
// Only hard-redirect for requests outside the React router context (e.g. WS).
api.interceptors.response.use(
  (res) => res,
  (err) => Promise.reject(err)
)

export default api
