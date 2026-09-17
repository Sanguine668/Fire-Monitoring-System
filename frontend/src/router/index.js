import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '监控总览', sub: '园区重点区域安全态势实时监测' } },
  { path: '/monitor', name: 'monitor', component: () => import('../views/MonitorView.vue'), meta: { title: '实时监控', sub: 'AI 视频分析与火灾烟雾识别' } },
  { path: '/phone', name: 'phone', component: () => import('../views/PhoneWizardView.vue'), meta: { title: '手机接入向导', sub: '手机摄像头推流接入与验证' } },
  { path: '/alarms', name: 'alarms', component: () => import('../views/AlarmsView.vue'), meta: { title: '告警中心', sub: '统一处置烟雾、明火及高风险事件' } },
  { path: '/cameras', name: 'cameras', component: () => import('../views/CamerasView.vue'), meta: { title: '视频源管理', sub: 'RTSP / 视频流设备统一管理' } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', sub: '检测阈值、告警策略与模型参数配置' } }
]

export default createRouter({ history: createWebHashHistory(), routes })
