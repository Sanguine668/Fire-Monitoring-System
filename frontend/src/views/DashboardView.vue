<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'

const metrics = ref([
  { label: '监控点位', value: '4', unit: '路', tone: 'primary' },
  { label: '今日告警', value: '0', unit: '条', tone: 'danger' },
  { label: '严重告警', value: '0', unit: '条', tone: 'warning' },
  { label: '待处理', value: '0', unit: '条', tone: 'success' }
])

const trend = [
  { day: '周一', count: 2 },
  { day: '周二', count: 4 },
  { day: '周三', count: 1 },
  { day: '周四', count: 5 },
  { day: '周五', count: 3 },
  { day: '周六', count: 6 },
  { day: '今日', count: 2 }
]

let chart = null

function renderChart() {
  chart = echarts.init(document.getElementById('trendChart'))
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: trend.map(t => t.day) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      name: '告警数',
      type: 'bar',
      barWidth: 28,
      data: trend.map(t => t.count),
      itemStyle: { color: '#e5484d', borderRadius: [4, 4, 0, 0] }
    }]
  })
}

const onResize = () => chart && chart.resize()
onMounted(() => {
  renderChart()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart && chart.dispose()
})
</script>

<template>
  <div class="dashboard">
    <el-row :gutter="16">
      <el-col v-for="m in metrics" :key="m.label" :span="6">
        <el-card shadow="never">
          <div class="metric">
            <span>{{ m.label }}</span>
            <strong>{{ m.value }}<small>{{ m.unit }}</small></strong>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-card shadow="never" class="chart-card">
      <template #header>本周告警趋势</template>
      <div id="trendChart" style="height: 320px" />
    </el-card>
  </div>
</template>

<style scoped>
.metric span { color: #7b8494; }
.metric strong { display: block; font-size: 26px; margin-top: 6px; }
.metric small { font-size: 13px; color: #9aa2b0; margin-left: 4px; font-weight: 400; }
.chart-card { margin-top: 16px; }
</style>
