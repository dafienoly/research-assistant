# V5 前端修复验证报告
日期: 2026-07-09 16:45

## 修复内容

### ❌→✅ SemiTheme (半导体主题)
- **根因**: `useMemo` 在早期 return 之后调用 → React #310 (hooks 顺序不一致)
- **修复**: 将所有 `useMemo` 和变量定义**移到**早期 return 之前，保证所有渲染路径 hooks 数量一致
- **验证结果**: 页面正常渲染, ECharts 曲线/细分方向热力图/ETF 表格全部正常

### ❌→✅ QMTSpot (QMT 实盘)
- **根因1**: `fmtMoney(v)` 在 `v` 为 undefined 时调用 `.toLocaleString()` → TypeError
- **根因2**: `positions/orders/trades/planPositions` 用 `?? []` 但不防非数组 → `rawData.some` 
- **修复1**: `fmtMoney` 加 null/undefined/isNaN 保护
- **修复2**: `PnLColored` 加 null/undefined/isNaN 保护
- **修复3**: 所有 column render 函数改用 safeFixed/safeLocale/safePercent 安全格式化
- **修复4**: 所有 dataSource 用 `Array.isArray()` 保护
- **验证结果**: 页面正常渲染, QMT 在线状态/资产卡片/持仓表格全部正常

### ❌→✅ TaskCenter (任务中心)
- **根因**: `result?.data ?? []` — `??` 只防 null/undefined, 不防非数组(如对象) → antd InternalTable 调用 `.some()` → crash
- **修复**: 用 `Array.isArray(raw) ? raw : []` 替代 `?? []`
- **验证结果**: 页面正常渲染, 显示空状态"暂无任务记录"

## 快速修复总结

| 模式 | 修复方式 | 涉及文件 |
|------|----------|----------|
| hooks 在 early return 后 | useMemo/useEffect 移到 return 前 | SemiTheme.tsx |
| `?? []` 不防非数组 | `Array.isArray(x) ? x : []` | TaskCenter.tsx, QMTSpot.tsx |
| 数值格式化未保护 | safeFixed/safeLocale/safePercent 辅助函数 | QMTSpot.tsx |
| `v.toFixed()`/`v.toLocaleString()` 无 null 保护 | 加 `v == null || isNaN(v)` 守卫 | QMTSpot.tsx |

## 最终验证后 Self-Verify 状态

| # | 路由 | 修复前 | 修复后 |
|---|------|--------|--------|
| 4 | /semi | ❌ ErrorBoundary #310 | ✅ PASS |
| 8 | /qmt | ❌ toLocaleString + rawData.some | ✅ PASS |
| 16 | /tasks | ❌ rawData.some | ✅ PASS |

**21/21 全 PASS.**
