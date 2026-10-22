import { computed, reactive } from 'vue'

const state = reactive({
  connected: false,
  detections: {},
  alarms: [],
  traces: [],
  lastAlarm: null,
  lastDetectionAt: 0
})

let socket = null
let reconnectTimer = null

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${protocol}://${location.host}/ws/events`)

  socket.onopen = () => {
    state.connected = true
    socket.send('hello')
  }
  socket.onmessage = (event) => {
    let data
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    if (data.event === 'detection') {
      state.detections[data.camera_id] = data
      if (data.agents) {
        state.traces.unshift({
          camera_id: data.camera_id,
          timestamp: data.timestamp,
          status: data.status,
          risk: data.risk_score,
          fps: data.fps,
          tiled: data.tiled,
          objects: (data.objects || []).length,
          agents: data.agents
        })
        state.traces = state.traces.slice(0, 80)
      }
      state.lastDetectionAt = Date.now()
    } else if (data.event === 'alarm') {
      const alarm = { ...data.alarm, seen: false }
      state.alarms.unshift(alarm)
      state.alarms = state.alarms.slice(0, 200)
      state.lastAlarm = alarm
    } else if (data.event === 'camera_online' || data.event === 'camera_offline') {
      state.detections[data.camera_id] = {
        ...(state.detections[data.camera_id] || {}),
        camera_id: data.camera_id,
        online: data.event === 'camera_online'
      }
    }
  }
  socket.onclose = () => {
    state.connected = false
    clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(connect, 2000)
  }
  socket.onerror = () => {
    state.connected = false
  }
}

const unreadCount = computed(
  () => new Set(
    state.alarms
      .filter((item) => !item.seen && item.status === 'unhandled')
      .map((item) => item.id)
  ).size
)
const unhandledCount = computed(
  () => new Set(
    state.alarms
      .filter((item) => item.status === 'unhandled')
      .map((item) => item.id)
  ).size
)

function markAllSeen() {
  state.alarms.forEach((item) => {
    item.seen = true
  })
}

function markHandled({ id, camera_id, alarm_type }) {
  state.alarms.forEach((item) => {
    const sameId = id !== undefined && item.id === id
    const sameGroup = camera_id !== undefined
      && item.camera_id === camera_id
      && item.alarm_type === alarm_type
    if (sameId || sameGroup) {
      item.status = 'handled'
      item.seen = true
    }
  })
}

function syncAlarms(rows) {
  const byId = new Map((rows || []).map((row) => [row.id, row]))
  state.alarms = state.alarms
    .filter((item) => byId.has(item.id))
    .map((item) => ({ ...byId.get(item.id), seen: item.seen ?? true }))
}

function clearSessionAlarms() {
  state.alarms = []
}

export function useRealtime() {
  if (!socket) connect()
  return {
    realtime: state,
    unreadCount,
    unhandledCount,
    markAllSeen,
    markHandled,
    syncAlarms,
    clearSessionAlarms
  }
}
