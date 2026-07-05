---
version: alpha
name: Hermes Design System
description: 暗色功能型界面设计规范，适用于 Dashboard 和 Agent Console。
colors:
  surface: "#0b1020"
  surface_card: "#121a35"
  surface_header: "#111832"
  surface_diagnostic: "#080d1c"
  border: "#26304f"
  text_primary: "#e8ecf8"
  text_secondary: "#9aa7c7"
  text_bright: "#cdd6f8"
  accent_cyan: "#00bcd4"
  accent_green: "#7df0bd"
  accent_green_bg: "#0f3d2e"
  accent_yellow: "#ffdc7a"
  accent_yellow_bg: "#44380c"
  accent_red: "#ff8ba0"
  accent_red_bg: "#4a1620"
  bar_gradient_start: "#73daca"
  bar_gradient_end: "#7aa2f7"
typography:
  fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
  mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace
  body:
    fontSize: 13px
  h1:
    fontSize: 22px
    fontWeight: 700
  h2:
    fontSize: 15px
    color: "{colors.text_bright}"
  h3:
    fontSize: 14px
    color: "{colors.text_bright}"
  label:
    fontSize: 12px
    color: "{colors.text_secondary}"
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  xxl: 24px
rounded:
  sm: 8px
  md: 12px
  lg: 14px
  full: 999px
components:
  card:
    backgroundColor: "{colors.surface_card}"
    borderColor: "{colors.border}"
    borderRadius: "{rounded.lg}"
    padding: "{spacing.lg}"
  card-header:
    backgroundColor: "{colors.surface_header}"
    borderBottom: "1px solid {colors.border}"
    padding: "{spacing.xl} {spacing.xxl}"
  button:
    backgroundColor: "{colors.surface_card}"
    borderColor: "{colors.border}"
    borderRadius: "{rounded.sm}"
    padding: "{spacing.sm} {spacing.md}"
    color: "{colors.text_primary}"
    fontSize: 14px
  button-hover:
    backgroundColor: "#1e2a4a"
  badge-green:
    backgroundColor: "{colors.accent_green_bg}"
    color: "{colors.accent_green}"
    borderRadius: "{rounded.full}"
    padding: "{spacing.xs} {spacing.sm}"
  badge-yellow:
    backgroundColor: "{colors.accent_yellow_bg}"
    color: "{colors.accent_yellow}"
    borderRadius: "{rounded.full}"
    padding: "{spacing.xs} {spacing.sm}"
  badge-red:
    backgroundColor: "{colors.accent_red_bg}"
    color: "{colors.accent_red}"
    borderRadius: "{rounded.full}"
    padding: "{spacing.xs} {spacing.sm}"
  diagnostic-panel:
    backgroundColor: "{colors.surface_diagnostic}"
    border: "1px solid {colors.border}"
    borderRadius: "{rounded.sm}"
    padding: "{spacing.sm}"
    fontSize: 12px
  answer-area:
    backgroundColor: "{colors.surface_card}"
    border: "1px solid {colors.border}"
    borderRadius: "{rounded.sm}"
    padding: "{spacing.lg}"
    fontSize: 14px
    lineHeight: 1.6
  progress-bar:
    height: 12px
    backgroundColor: "#202946"
    borderRadius: "{rounded.full}"
    gradient: "{colors.bar_gradient_start} → {colors.bar_gradient_end}"
  textarea:
    backgroundColor: "{colors.surface_card}"
    border: "1px solid {colors.border}"
    borderRadius: "{rounded.sm}"
    color: "{colors.text_primary}"
    fontSize: 13px

---

## Overview

Hermes Design System 是一套针对量化投研工具链的暗色主题设计规范。所有组件以信息密度和可读性为优先，辅助色用于功能状态（运行中/成功/失败/警告），非装饰用途。

## Colors

- **surface (#0b1020):** 主背景，降低视觉疲劳，适配长时间监控。
- **surface_card (#121a35):** 卡片和控件背景，与主背景形成层次。
- **border (#26304f):** 低对比度边界线，不抢内容注意力。
- **accent_green (#7df0bd):** 运行中、成功、通过状态。
- **accent_yellow (#ffdc7a):** 待定、警告、缓冲状态。
- **accent_red (#ff8ba0):** 失败、错误、阻断状态。

## Typography

系统字体栈提升跨平台一致性。等宽字体 `mono` 用于日志、诊断、代码片段、token hash 等机器可读内容。12px 标签用于辅助信息，13px 正文用于面板内容，14-22px 用于标题层级。

## Components

`card` 和 `card-header` 构成大部分页面的骨架。`badge-*` 三色标签用于状态指示。`diagnostic-panel` 专门用于折叠的诊断输出区域，有别于 `answer-area` 主回答区域。`button-hover` 通过颜色加深表示交互状态，不使用额外边框变化。
