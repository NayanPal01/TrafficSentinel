import { useState, useEffect } from 'react'

const NAV_TABS = ['Live View', 'Playback', 'Analytics', 'ANPR Trace', 'Device']

interface TopNavProps {
  activeTab: string
  onTabChange: (tab: string) => void
}

export default function TopNav({ activeTab, onTabChange }: TopNavProps) {
  const [time, setTime] = useState(new Date())
  const [muted, setMuted] = useState(false)

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  const clockStr = time.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  return (
    <header
      style={{
        height: 50,
        background: '#161c28',
        borderBottom: '1px solid #262f40',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: 0,
        zIndex: 50,
        boxShadow: '0 2px 12px rgba(0,0,0,0.5)',
        userSelect: 'none',
      }}
    >
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 220 }}>
        <div
          style={{
            width: 30,
            height: 30,
            background: 'linear-gradient(135deg, #00d2ff22, #00d2ff44)',
            border: '1px solid #00d2ff55',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" stroke="#00d2ff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="13" r="3" stroke="#00d2ff" strokeWidth="1.5" />
            <path d="M17 4l3 2.5" stroke="#00d2ff" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#ffffff', letterSpacing: '0.02em', lineHeight: 1.1 }}>
            DSS TrafficSentinel
          </div>
          <div style={{ fontSize: 9, fontWeight: 500, color: '#00d2ff', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
            AI Platform
          </div>
        </div>
      </div>

      {/* Center Nav Tabs */}
      <nav style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 2, height: '100%' }}>
        {NAV_TABS.map((tab) => {
          const isActive = tab === activeTab
          return (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              style={{
                height: '100%',
                padding: '0 18px',
                background: 'none',
                border: 'none',
                borderBottom: isActive ? '2px solid #00d2ff' : '2px solid transparent',
                color: isActive ? '#00d2ff' : '#a0aec0',
                fontSize: 12.5,
                fontWeight: isActive ? 600 : 400,
                cursor: 'pointer',
                letterSpacing: '0.02em',
                transition: 'all 0.15s ease',
                fontFamily: 'Inter, sans-serif',
                whiteSpace: 'nowrap',
              }}
              onMouseEnter={(e) => {
                if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = '#d1e8f0'
              }}
              onMouseLeave={(e) => {
                if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = '#a0aec0'
              }}
            >
              {tab}
            </button>
          )
        })}
      </nav>

      {/* Right Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 280, justifyContent: 'flex-end' }}>
        {/* Bell */}
        <div style={{ position: 'relative' }}>
          <IconBtn title="Notifications">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M13.73 21a2 2 0 01-3.46 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </IconBtn>
          <span
            style={{
              position: 'absolute',
              top: 2,
              right: 2,
              width: 14,
              height: 14,
              background: '#2ed573',
              borderRadius: '50%',
              fontSize: 8,
              fontWeight: 700,
              color: '#000',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            0
          </span>
        </div>

        {/* Mute */}
        <IconBtn title={muted ? 'Unmute' : 'Mute'} onClick={() => setMuted(!muted)} active={muted}>
          {muted ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M11 5L6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M23 9l-6 6M17 9l6 6" stroke="#ff4757" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M11 5L6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          )}
        </IconBtn>

        {/* Grid view */}
        <IconBtn title="Grid View">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="3" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="3" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <rect x="14" y="14" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </IconBtn>

        {/* Clock */}
        <div
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 13,
            fontWeight: 600,
            color: '#00d2ff',
            background: '#0d1117',
            border: '1px solid #262f40',
            borderRadius: 4,
            padding: '3px 10px',
            letterSpacing: '0.08em',
            minWidth: 80,
            textAlign: 'center',
          }}
        >
          {clockStr}
        </div>

        {/* Avatar */}
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #00d2ff, #0077b6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            color: '#fff',
            cursor: 'pointer',
            border: '1px solid #00d2ff55',
          }}
          title="Admin User"
        >
          AD
        </div>

        {/* Window controls */}
        <div style={{ display: 'flex', gap: 5, marginLeft: 6 }}>
          <WinBtn color="#ffa502" title="Minimize">–</WinBtn>
          <WinBtn color="#2ed573" title="Maximize">□</WinBtn>
          <WinBtn color="#ff4757" title="Close">×</WinBtn>
        </div>
      </div>
    </header>
  )
}

function IconBtn({
  children,
  title,
  onClick,
  active,
}: {
  children: React.ReactNode
  title?: string
  onClick?: () => void
  active?: boolean
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 30,
        height: 30,
        background: active ? 'rgba(0,210,255,0.12)' : 'transparent',
        border: '1px solid ' + (active ? '#00d2ff44' : 'transparent'),
        borderRadius: 6,
        color: active ? '#00d2ff' : '#a0aec0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        fontFamily: 'Inter, sans-serif',
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.background = 'rgba(0,210,255,0.08)'
        el.style.color = '#fff'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.background = active ? 'rgba(0,210,255,0.12)' : 'transparent'
        el.style.color = active ? '#00d2ff' : '#a0aec0'
      }}
    >
      {children}
    </button>
  )
}

function WinBtn({ color, title, children }: { color: string; title: string; children: React.ReactNode }) {
  return (
    <button
      title={title}
      style={{
        width: 14,
        height: 14,
        borderRadius: '50%',
        background: color,
        border: 'none',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 8,
        color: 'transparent',
        transition: 'color 0.1s',
        fontFamily: 'Inter, sans-serif',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = '#00000099' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = 'transparent' }}
    >
      {children}
    </button>
  )
}
