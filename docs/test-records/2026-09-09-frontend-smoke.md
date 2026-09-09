# 2026-09-09 前端基础页面冒烟记录

结果：通过

检查项（自动化验证）：
- `npm run build` 成功，五个页面均生成独立 chunk；
- Vite dev server 正常启动（http://localhost:5173）；
- `/` 与五个视图模块 HTTP 均为 200。

待人工补充（浏览器内点击验收）：
- 侧栏五菜单路由切换与标题显示；
- Dashboard ECharts 图表渲染 7 根柱。
