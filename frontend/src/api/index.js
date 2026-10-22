const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function request(url, options = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 12000)
  const opts = { ...options, signal: controller.signal }
  if (opts.body && typeof opts.body === 'string' && !opts.headers) {
    opts.headers = JSON_HEADERS
  }
  try {
    const res = await fetch(url, opts)
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const data = await res.json()
        detail = data.detail || detail
      } catch {
        /* 保留默认错误信息 */
      }
      throw new Error(detail)
    }
    const type = res.headers.get('content-type') || ''
    return type.includes('application/json') ? res.json() : res.text()
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请检查后端是否在线')
    throw error
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  health: () => request('/api/health'),
  network: () => request('/api/network'),
  probe: (payload) => request('/api/probe', { method: 'POST', body: JSON.stringify(payload) }),
  probePhone: (payload) => request('/api/probe_phone', { method: 'POST', body: JSON.stringify(payload) }),
  cameras: () => request('/api/cameras'),
  addCamera: (payload) => request('/api/cameras', { method: 'POST', body: JSON.stringify(payload) }),
  toggleCamera: (id) => request(`/api/cameras/${id}/toggle`, { method: 'POST' }),
  deleteCamera: (id) => request(`/api/cameras/${id}`, { method: 'DELETE' }),
  uploadVideo: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/uploads', { method: 'POST', body: form })
  },
  alarms: (limit = 200) => request(`/api/alarms?limit=${limit}`),
  clearAlarms: () => request('/api/alarms', { method: 'DELETE' }),
  modelInfo: () => request('/api/model'),
  agents: () => request('/api/agents'),
  ackAlarm: (id) => request(`/api/alarms/${id}/ack`, { method: 'POST' }),
  ackAlarmGroup: (payload) => request('/api/alarms/ack_group', { method: 'POST', body: JSON.stringify(payload) }),
  dashboard: () => request('/api/dashboard'),
  settings: () => request('/api/settings'),
  saveSettings: (payload) => request('/api/settings', { method: 'PUT', body: JSON.stringify(payload) })
}

export const streamUrl = (cameraId, annotated = true) => `/stream/${cameraId}${annotated ? '' : '?annotated=false'}`
export const snapshotUrl = (cameraId, annotated = true) => `/snapshot/${cameraId}?annotated=${annotated ? 'true' : 'false'}`
