import { computed, reactive } from 'vue'

const state = reactive({
  connected: false,
  detections: {},
  alarms: [],
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
      state.lastDetectionAt = Date.now()
    } else if (data.event === 'alarm') {
      state.alarms.unshift(data.alarm)
      state.alarms = state.alarms.slice(0, 200)
      state.lastAlarm = data.alarm
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

export function useRealtime() {
  if (!socket) connect()
  return {
    realtime: state,
    unhandledCount: computed(() => state.alarms.filter((item) => item.status === 'unhandled').length)
  }
}
