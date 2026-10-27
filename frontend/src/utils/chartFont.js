/**
 * 图表字号跟随全局字号总开关（html 的 font-size，见 styles/base.css）。
 * ECharts 画在 canvas 上，不继承 CSS 字号，需要在这里显式换算。
 */
export function chartFont() {
  const root = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  return Math.round(root * 0.8)
}
