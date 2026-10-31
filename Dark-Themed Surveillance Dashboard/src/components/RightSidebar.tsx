import { useState, useEffect } from 'react'

type FilterTab = 'All' | 'Violations' | 'ANPR' | 'Vehicles'

interface ANPREvent {
  id: string
  plate: string
  vehicleType: string
  vehicleColor: string
  source: string
  timestamp: string
  violation?: string
  plateImg: string
}

const EVENTS: ANPREvent[] = [
  {
    id: 'e1',
    plate: 'MH12AB1234',
    vehicleType: 'Motor Vehicle',
    vehicleColor: 'Black',
    source: 'Current Site-Exit',
    timestamp: '2025-08-27  10:39:48',
    plateImg: 'MH12AB1234',
  },
  {
    id: 'e2',
    plate: '2BR-4269',
    vehicleType: 'Motor Vehicle',
    vehicleColor: 'White',
    source: 'Current Site-Entrance',
    timestamp: '2025-08-27  10:39:31',
    violation: 'Speed Violation',
    plateImg: '2BR-4269',
  },
]

export default function RightSidebar() {
  const [filterTab, setFilterTab] = useState<FilterTab>('All')
  const [paused, setPaused] = useState(false)
  const [events, setEvents] = useState<ANPREvent[]>(EVENTS)

  useEffect(() => {
    const fetchRecentEvents = () => {
      fetch('http://localhost:8765/api/events')
        .then((res) => res.json())
        .then((data: ANPREvent[]) => {
          if (Array.isArray(data) && data.length > 0) {
            setEvents(data)
          }
        })
        .catch(() => {})
    }

    // Initial fetch from backend DB
    fetchRecentEvents()
    const syncTimer = setInterval(fetchRecentEvents, 2000)

    // Connect live WebSocket
    let ws: WebSocket | null = null
    const connectWs = () => {
      ws = new WebSocket('ws://localhost:8765/ws/events')
      ws.onmessage = (event) => {
        if (paused) return
        try {
          const payload = JSON.parse(event.data)
          if (payload.type === 'anpr_detect' || payload.type === 'violation') {
            setEvents((prev) => {
              const pClean = (payload.plate || '').trim().toUpperCase()
              const pNorm = pClean.replace(/[^A-Z0-9]/g, '')
              const idx = prev.findIndex((e) => {
                if (pNorm && pNorm !== 'UNREAD') {
                  const epNorm = (e.plate || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '')
                  if (epNorm && epNorm === pNorm) return true
                }
                return e.id && e.id === payload.id
              })
              if (idx >= 0) {
                const updated = [...prev]
                updated[idx] = {
                  ...updated[idx],
                  ...payload,
                  plateImg: (payload.plateImg && !payload.plateImg.includes('/crops/')) ? payload.plateImg : updated[idx].plateImg,
                  violation: payload.violation || updated[idx].violation,
                  fine: payload.fine || updated[idx].fine,
                }
                return updated
              }
              return [payload, ...prev.slice(0, 49)]
            })
          }
        } catch (e) {}
      }
      ws.onclose = () => {
        setTimeout(connectWs, 2000)
      }
      ws.onerror = () => {
        try { ws?.close() } catch (e) {}
      }
    }

    connectWs()

    return () => {
      clearInterval(syncTimer)
      if (ws) ws.close()
    }
  }, [paused])

  const filtered = events.filter((e) => {
    if (filterTab === 'All') return true
    if (filterTab === 'Violations') return !!e.violation
    if (filterTab === 'ANPR') return true
    if (filterTab === 'Vehicles') return e.vehicleType !== 'Two-Wheeler'
    return true
  })

  return (
    <aside
      style={{
        width: 340,
        height: '100%',
        background: '#161c28',
        borderLeft: '1px solid #262f40',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Top control bar */}
      <div
        style={{
          padding: '10px 12px 8px',
          borderBottom: '1px solid #262f40',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 11.5, fontWeight: 600, color: '#ffffff', letterSpacing: '0.04em' }}>
            ANPR Event Feed
          </div>
          <div style={{ display: 'flex', gap: 5 }}>
            <ControlBtn
              label={paused ? '▶ Resume' : '⏸ Pause'}
              active={paused}
              onClick={() => setPaused(!paused)}
            />
            <ControlBtn label="Clear" onClick={() => setEvents([])} danger />
          </div>
        </div>

        {/* Filter tabs */}
        <div style={{ display: 'flex', gap: 3 }}>
          {(['All', 'Violations', 'ANPR', 'Vehicles'] as FilterTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setFilterTab(t)}
              style={{
                flex: 1,
                padding: '4px 0',
                background: filterTab === t ? 'rgba(0,210,255,0.12)' : 'transparent',
                border: `1px solid ${filterTab === t ? '#00d2ff44' : '#262f40'}`,
                borderRadius: 4,
                color: filterTab === t ? '#00d2ff' : '#a0aec0',
                fontSize: 10,
                fontWeight: filterTab === t ? 600 : 400,
                cursor: 'pointer',
                fontFamily: 'Inter, sans-serif',
                transition: 'all 0.15s',
                letterSpacing: '0.04em',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Count indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: paused ? '#ffa502' : '#2ed573',
              boxShadow: paused ? '0 0 6px #ffa502' : '0 0 6px #2ed573',
            }}
          />
          <span style={{ fontSize: 10, color: '#a0aec0', fontFamily: 'Inter, sans-serif' }}>
            {paused ? 'Feed paused' : `${filtered.length} event${filtered.length !== 1 ? 's' : ''} — live`}
          </span>
        </div>
      </div>

      {/* Scrollable event feed */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.length === 0 ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#4a5a72',
              fontSize: 12,
              fontFamily: 'Inter, sans-serif',
              marginTop: 40,
            }}
          >
            No events to display
          </div>
        ) : (
          filtered.map((event) => <ANPRCard key={event.id} event={event} />)
        )}
      </div>

      {/* Footer stats */}
      <div
        style={{
          borderTop: '1px solid #262f40',
          padding: '8px 12px',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          gap: 4,
        }}
      >
        <StatChip label="Today" value="1,284" />
        <StatChip label="Violations" value="37" color="#ff4757" />
        <StatChip label="Matched" value="12" color="#2ed573" />
      </div>
    </aside>
  )
}

function ANPRCard({ event }: { event: ANPREvent }) {
  const [hovered, setHovered] = useState(false)

  const colorMap: Record<string, string> = {
    Black: '#374151',
    White: '#d1d5db',
    Red: '#ef4444',
    Silver: '#9ca3af',
    Blue: '#3b82f6',
  }
  const colorHex = colorMap[event.vehicleColor] ?? '#6b7280'

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: '#0d1117',
        border: `1px solid ${hovered ? 'rgba(0,210,255,0.35)' : '#262f40'}`,
        borderRadius: 8,
        overflow: 'hidden',
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        boxShadow: hovered ? '0 0 12px rgba(0,210,255,0.12)' : 'none',
        transform: hovered ? 'translateY(-1px)' : 'translateY(0)',
      }}
    >
      {/* Card header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          background: '#0a0f14',
          borderBottom: '1px solid #1a2236',
        }}
      >
        <span
          style={{
            padding: '1px 7px',
            background: 'rgba(0,210,255,0.15)',
            border: '1px solid #00d2ff44',
            borderRadius: 3,
            fontSize: 9,
            fontWeight: 700,
            color: '#00d2ff',
            letterSpacing: '0.1em',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          ANPR
        </span>
        {event.violation && (
          <span
            style={{
              padding: '1px 7px',
              background: 'rgba(255,71,87,0.15)',
              border: '1px solid #ff475744',
              borderRadius: 3,
              fontSize: 9,
              fontWeight: 700,
              color: '#ff4757',
              letterSpacing: '0.08em',
              fontFamily: 'Inter, sans-serif',
            }}
          >
            {event.violation}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9.5, color: '#4a5a72', fontFamily: 'Inter, sans-serif' }}>
          {event.source}
        </span>
      </div>

      {/* Timestamp row */}
      <div style={{ padding: '4px 10px 0', display: 'flex', justifyContent: 'flex-end' }}>
        <span style={{ fontSize: 9, color: '#4a5a72', fontFamily: "'JetBrains Mono', monospace" }}>
          {event.timestamp}
        </span>
      </div>

      {/* Card body */}
      <div style={{ display: 'flex', gap: 10, padding: '8px 10px 10px' }}>
        {/* Plate image thumbnail */}
        <div
          style={{
            width: 92,
            height: 48,
            background: '#101520',
            borderRadius: 5,
            border: `1.5px solid ${event.violation ? '#ff4757' : '#00d2ff'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            overflow: 'hidden',
          }}
        >
          {event.plateImg && !event.plateImg.includes('/crops/') ? (
            <img
              src={event.plateImg.startsWith('http') ? event.plateImg : (event.plateImg.startsWith('/') ? event.plateImg : `/${event.plateImg}`)}
              alt="Plate"
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              onError={(e) => {
                (e.target as HTMLElement).style.display = 'none'
              }}
            />
          ) : (
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, fontWeight: 700, color: '#00d2ff' }}>
              IND
            </span>
          )}
        </div>

        {/* Details */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 15,
              fontWeight: 700,
              color: '#ffffff',
              letterSpacing: '0.08em',
              lineHeight: 1.1,
            }}
          >
            {event.plate}
          </div>
          <div style={{ display: 'flex', gap: 5, alignItems: 'center', marginTop: 2 }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
              <path d="M19 17H5a2 2 0 01-2-2V9a2 2 0 012-2h14a2 2 0 012 2v6a2 2 0 01-2 2z" stroke="#a0aec0" strokeWidth="1.5" />
              <circle cx="7" cy="17" r="2" stroke="#a0aec0" strokeWidth="1.5" />
              <circle cx="17" cy="17" r="2" stroke="#a0aec0" strokeWidth="1.5" />
            </svg>
            <span style={{ fontSize: 10.5, color: '#a0aec0', fontFamily: 'Inter, sans-serif' }}>
              {event.vehicleType}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: colorHex,
                border: '1px solid rgba(255,255,255,0.15)',
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 10.5, color: '#a0aec0', fontFamily: 'Inter, sans-serif' }}>
              {event.vehicleColor}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ControlBtn({
  label,
  active,
  danger,
  onClick,
}: {
  label: string
  active?: boolean
  danger?: boolean
  onClick?: () => void
}) {
  const base = danger ? 'rgba(255,71,87,0.1)' : active ? 'rgba(255,165,2,0.12)' : '#1a2236'
  const borderBase = danger ? '#ff475744' : active ? '#ffa50244' : '#262f40'
  const colorBase = danger ? '#ff4757' : active ? '#ffa502' : '#a0aec0'

  return (
    <button
      onClick={onClick}
      style={{
        padding: '4px 10px',
        background: base,
        border: `1px solid ${borderBase}`,
        borderRadius: 5,
        color: colorBase,
        fontSize: 10.5,
        fontWeight: 500,
        cursor: 'pointer',
        fontFamily: 'Inter, sans-serif',
        whiteSpace: 'nowrap',
        transition: 'all 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.opacity = '0.85'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.opacity = '1'
      }}
    >
      {label}
    </button>
  )
}

function StatChip({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: color ?? '#ffffff', fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </div>
      <div style={{ fontSize: 9, color: '#4a5a72', fontFamily: 'Inter, sans-serif', marginTop: 1, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        {label}
      </div>
    </div>
  )
}
