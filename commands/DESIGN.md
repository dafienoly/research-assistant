---
version: alpha
name: Hermes Dashboard
description: 现代化亮色仪表盘设计系统 — 极简、信息优先、数据驱动。
colors:
  primary: "#0F172A"
  secondary: "#64748B"
  tertiary: "#2563EB"
  tertiary-light: "#DBEAFE"
  neutral: "#F8FAFC"
  surface: "#FFFFFF"
  surface-secondary: "#F1F5F9"
  border: "#E2E8F0"
  on-primary: "#FFFFFF"
  on-tertiary: "#FFFFFF"
  success: "#059669"
  success-bg: "#D1FAE5"
  warning: "#D97706"
  warning-bg: "#FEF3C7"
  error: "#DC2626"
  error-bg: "#FEE2E2"
  chart-1: "#2563EB"
  chart-2: "#059669"
  chart-3: "#D97706"
  chart-4: "#7C3AED"
  text-primary: "#0F172A"
  text-secondary: "#64748B"
  text-muted: "#94A3B8"
typography:
  h1:
    fontFamily: Inter, -apple-system, "Segoe UI", sans-serif
    fontSize: 1.5rem
    fontWeight: 700
    lineHeight: 1.2
  h2:
    fontFamily: Inter, -apple-system, "Segoe UI", sans-serif
    fontSize: 1.125rem
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: Inter, -apple-system, "Segoe UI", sans-serif
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Inter, -apple-system, "Segoe UI", sans-serif
    fontSize: 0.75rem
    fontWeight: 500
    color: "{colors.text-secondary}"
  mono:
    fontFamily: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace
    fontSize: 0.8125rem
    lineHeight: 1.5
rounded:
  sm: 6px
  md: 10px
  lg: 16px
  xl: 24px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
components:
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    borderColor: "{colors.border}"
    borderWidth: 1px
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
    boxShadow: "0 1px 3px 0 rgb(0 0 0 / 0.04)"
  card-hover:
    boxShadow: "0 4px 12px 0 rgb(0 0 0 / 0.08)"
  stat-card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
    borderLeft: "4px solid {colors.tertiary}"
  stat-card-success:
    borderLeft: "4px solid {colors.success}"
  stat-card-warning:
    borderLeft: "4px solid {colors.warning}"
  stat-card-error:
    borderLeft: "4px solid {colors.error}"
  progress-bar:
    height: 8px
    backgroundColor: "{colors.surface-secondary}"
    rounded: "{rounded.full}"
    fillColor: "{colors.tertiary}"
    transition: "width 0.5s ease"
  progress-bar-success:
    fillColor: "{colors.success}"
  progress-bar-warning:
    fillColor: "{colors.warning}"
  gauge:
    width: 120px
    height: 120px
    strokeWidth: 8px
    trackColor: "{colors.surface-secondary}"
    fillColor: "{colors.tertiary}"
  badge:
    fontSize: 0.75rem
    fontWeight: 600
    padding: "{spacing.xs} {spacing.sm}"
    rounded: "{rounded.full}"
  badge-success:
    backgroundColor: "{colors.success-bg}"
    color: "{colors.success}"
  badge-warning:
    backgroundColor: "{colors.warning-bg}"
    color: "{colors.warning}"
  badge-error:
    backgroundColor: "{colors.error-bg}"
    color: "{colors.error}"
  badge-info:
    backgroundColor: "{colors.tertiary-light}"
    color: "{colors.tertiary}"
  sidebar:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    width: 200px
  table:
    borderColor: "{colors.border}"
    headerBackground: "{colors.surface-secondary}"
    headerColor: "{colors.text-secondary}"
    rowHover: "{colors.surface-secondary}"
  metric:
    valueFontSize: 1.5rem
    valueFontWeight: 700
    labelFontSize: 0.75rem
    labelColor: "{colors.text-secondary}"
  status-dot:
    width: 8px
    height: 8px
    rounded: "{rounded.full}"
  status-dot-running:
    backgroundColor: "{colors.success}"
  status-dot-idle:
    backgroundColor: "{colors.text-muted}"
  status-dot-error:
    backgroundColor: "{colors.error}"
  status-dot-warning:
    backgroundColor: "{colors.warning}"
  input:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.sm}"
    padding: "{spacing.sm} {spacing.md}"
    fontSize: 0.875rem
  input-focus:
    borderColor: "{colors.tertiary}"
    boxShadow: "0 0 0 3px {colors.tertiary-light}"
---

## Overview

Hermes Dashboard 是一套面向量化投研监控的现代化亮色设计系统。以极简主义为基调，
信息密度高但视觉干净。颜色以 slate-blue 为基调，用绿色/黄色/红色表示运行状态，
蓝色作为主要交互色。所有组件设计以数据可读性和状态可感知性为优先。

## Colors

- **Primary (#0F172A):** 标题、正文、侧边栏背景 — 高对比度深色。
- **Secondary (#64748B):** 辅助文字、边框、标签 — 中等对比度。
- **Tertiary (#2563EB):** 交互驱动 — 按钮、链接、选中态、进度条填充。
- **Surface (#FFFFFF):** 卡片和页面背景。
- **Surface Secondary (#F1F5F9):** 表格表头、进度条轨道、分割区。
- **Border (#E2E8F0):** 卡片和表格的边界线。
- **Success (#059669) / Warning (#D97706) / Error (#DC2626):** 状态色，每种
  有配套的浅色背景用于 Badge。
- **Chart colors:** 四色序列用于版本进度图和数据可视化。

## Typography

Inter 系统字体栈，跨平台一致。正文 14px (0.875rem) 是最常用尺寸。
标签和辅助信息 12px (0.75rem)。mono 用于代码片段、日志、hash 等机器可读内容。

## Layout

间距基线 4px。卡片内间距 lg (16px)，卡片间间距 xl (24px)。
侧边栏固定 200px 宽，深色背景与亮色主区形成对比。

## Components

### Cards
`card` 是所有内容块的基础容器。白色背景 + 1px 边框 + 轻微阴影。
`stat-card` 带 4px 左边框颜色编码（蓝色=常规，绿=成功，黄=警告，红=错误）。

### Progress Bars
进度条 8px 高，圆形端点，蓝色填充。运行中版本使用 `progress-bar`，
已完成使用 `progress-bar-success`。

### Badges
状态标签用彩色背景 + 彩色文字，避免冗余图标。`badge-success` 用于已完成，
`badge-warning` 用于运行中/待定，`badge-error` 用于失败。

### Sidebar
深色侧边栏 (`#0F172A`) 白色文字，固定宽度。菜单项使用透明背景 + 白色文字，
选中态使用半透明白色底。

### Status Dots
小的圆形指示器 (8px) 用于实时状态展示：绿色=运行中，灰色=空闲，
红色=错误，黄色=警告。

### Tables
表头浅灰背景，内容白色。悬停行浅灰高亮。边框 `#E2E8F0`。

### Metrics
数据指标用大字号 (1.5rem) 加粗展示值，小字标签在上方。绿色/红色用于
正向/负向指标。

## Do's and Don'ts

- **Do** 使用 token reference 保持设计一致性。
- **Do** 用左边框颜色编码 stat-card，取代整块彩色背景。
- **Do** 在进度条中显示百分比文本，放在条末。
- **Don't** 使用亮色侧边栏 — 侧边栏保持 `{colors.primary}` 深色。
- **Don't** 在状态 Badge 中同时使用图标和颜色 — 二选一即可。
- **Don't** 使用阴影层级来表示重要性 — 用左边框颜色替代。
- **Don't** 在 status-dot 外再加文字状态标签 — dot 本身足够。
