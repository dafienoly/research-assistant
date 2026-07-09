import React from 'react'

export type DotStatus = 'running' | 'idle' | 'error' | 'warning'

interface StatusDotProps {
  status: DotStatus
  size?: number
  pulse?: boolean
  color?: string
}

const DOT_COLORS: Record<DotStatus, string> = {
  running: '#059669',
  idle: '#94A3B8',
  error: '#DC2626',
  warning: '#D97706',
}

/**
 * StatusDot — A colored circle indicator.
 * Use instead of inline <span> with hardcoded colors.
 *
 * @example
 *   <StatusDot status="running" />
 *   <StatusDot status="error" size={12} pulse />
 */
const StatusDot: React.FC<StatusDotProps> = ({ status = 'idle', size = 8, pulse = false, color: customColor }) => {
  const color = customColor || DOT_COLORS[status] || DOT_COLORS.idle

  return (
    <span
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        borderRadius: '50%',
        backgroundColor: color,
        verticalAlign: 'middle',
        flexShrink: 0,
        ...(pulse
          ? {
              animation: 'pulse 2s ease-in-out infinite',
            }
          : {}),
      }}
      aria-label={`Status: ${status}`}
    />
  )
}

export default StatusDot
