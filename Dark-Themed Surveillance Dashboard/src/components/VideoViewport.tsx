import { useState, useEffect } from 'react'

const STREAM_URL = 'http://localhost:8765/stream'
const STATS_URL = 'http://localhost:8765/api/stats'

const GRID_MODES = ['1×1', '2×2', '3×3'] as const
type GridMode = (typeof GRID_MODES)[number]

export default function VideoViewport() {
  const [gridMode, setGridMode] = useState<GridMode>('1×1')
  const [isRecording, setIsRecording] = useState(false)
  const [audioMuted, setAudioMuted] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [streamError, setStreamError] = useState(false)
  const [stats, setStats] = useState({ fps: 0, infer_ms: 0, active_tracks: 0, camera_id: 'CAM-01', light: 'GREEN' })
  const [liveLogs, setLiveLogs] = useState<any[]>([])
  const [timestamp, setTimestamp] = useState(new Date().toLocaleString())

  useEffect(() => {
    const timer = setInterval(() => {
      setTimestamp(new Date().toLocaleString())
      fetch(STATS_URL)
        .then((res) => res.json())
        .then((data) => setStats(data))
        .catch(() => {})

      fetch('http://localhost:8765/api/live-logs')
        .then((res) => res.json())
        .then((data) => {
          if (Array.isArray(data)) setLiveLogs(data)
        })
        .catch(() => {})
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const streamInfo = stats.pipeline_active
    ? `YOLO26 · ${stats.fps} FPS · ${stats.infer_ms}ms · Tracks: ${stats.active_tracks}`
    : `YOLO26 · STANDBY (Upload video or select source to start)`

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        background: '#0d1117',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Video Container */}
      <div
        style={{
          flex: 1,
          position: 'relative',
          background: '#111820',
          border: '1px solid #262f40',
          margin: '10px',
          borderRadius: 8,
          overflow: 'hidden',
          boxShadow: '0 0 0 1px #00d2ff22, 0 4px 24px rgba(0,0,0,0.7)',
        }}
      >
        {/* Live Video Stream when active, otherwise VideoBackground standby graphic */}
        {stats.pipeline_active && !streamError ? (
          <img
            src={STREAM_URL}
            onError={() => setStreamError(true)}
            alt="Live Stream"
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              display: 'block',
              background: '#0a0f14',
            }}
          />
        ) : (
          <VideoBackground />
        )}

        {/* Top info overlay */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            display: 'flex',
            alignItems: 'center',
            padding: '8px 12px',
            background: 'linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%)',
            zIndex: 10,
            backdropFilter: 'blur(2px)',
          }}
        >
          {/* Stream info */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
            <LiveIndicator />
            <span
              style={{
                fontSize: 10.5,
                color: '#a0aec0',
                fontFamily: "'JetBrains Mono', monospace",
                letterSpacing: '0.04em',
              }}
            >
              {streamInfo}
            </span>
          </div>

          {/* Timestamp */}
          <div
            style={{
              fontSize: 11,
              color: '#fff',
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: '0.06em',
              opacity: 0.85,
            }}
          >
            {timestamp}
          </div>

          {/* Tools */}
          <div style={{ display: 'flex', gap: 4, marginLeft: 14 }}>
            <VideoToolBtn title="Snapshot">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <circle cx="12" cy="13" r="4" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </VideoToolBtn>
            <VideoToolBtn
              title={isRecording ? 'Stop Recording' : 'Start Recording'}
              active={isRecording}
              onClick={() => setIsRecording(!isRecording)}
            >
              <div style={{
                width: isRecording ? 8 : 10,
                height: isRecording ? 8 : 10,
                borderRadius: isRecording ? 2 : '50%',
                background: isRecording ? '#ff4757' : 'currentColor',
                boxShadow: isRecording ? '0 0 8px #ff4757' : 'none',
              }} />
            </VideoToolBtn>
            <VideoToolBtn
              title={audioMuted ? 'Unmute' : 'Mute Audio'}
              active={audioMuted}
              onClick={() => setAudioMuted(!audioMuted)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M11 5L6 9H2v6h4l5 4V5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                {audioMuted ? (
                  <path d="M23 9l-6 6M17 9l6 6" stroke="#ff4757" strokeWidth="1.5" strokeLinecap="round" />
                ) : (
                  <path d="M15.54 8.46a5 5 0 010 7.07" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                )}
              </svg>
            </VideoToolBtn>
            <VideoToolBtn title="Digital Zoom">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="1.5" />
                <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M8 11h6M11 8v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </VideoToolBtn>
            <VideoToolBtn title="Fullscreen" onClick={() => setFullscreen(!fullscreen)}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M8 3H5a2 2 0 00-2 2v3M21 8V5a2 2 0 00-2-2h-3M16 21h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </VideoToolBtn>
          </div>
        </div>

        {/* ANPR Detection Overlay (upper-left floating) */}
        <div
          style={{
            position: 'absolute',
            top: 52,
            left: 12,
            zIndex: 10,
          }}
        >
          <DetectionBox plate="MH12AB1234" confidence={97.4} />
        </div>

        {/* Speed / STOP badge (bottom-right) */}
        <div
          style={{
            position: 'absolute',
            bottom: 52,
            right: 16,
            zIndex: 10,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            alignItems: 'flex-end',
          }}
        >
          <SpeedBadge label="STOP" color="#ff4757" />
          <SpeedBadge label="42 km/h" color="#ffa502" small />
        </div>

        {/* Grid overlay for multi-view */}
        {gridMode !== '1×1' && <GridOverlay mode={gridMode} />}
      </div>

      {/* Live AI Detection Logs Table (Restored Streamlit feature) */}
      <div
        style={{
          maxHeight: 130,
          margin: '0 10px 8px',
          background: '#161c28',
          border: '1px solid #262f40',
          borderRadius: 6,
          overflowY: 'auto',
          padding: 8,
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: 11, fontWeight: 700, color: '#00d2ff', marginBottom: 4 }}>
          📋 Live Vehicle & Violation Detection Logs
        </div>
        {liveLogs.length === 0 ? (
          <div style={{ fontSize: 11, color: '#a0aec0' }}>No active live violations detected in current frames.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10.5, textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #262f40', color: '#a0aec0' }}>
                <th style={{ padding: 4 }}>Type</th>
                <th style={{ padding: 4 }}>Track</th>
                <th style={{ padding: 4 }}>Plate</th>
                <th style={{ padding: 4 }}>Conf</th>
                <th style={{ padding: 4 }}>Status</th>
                <th style={{ padding: 4 }}>Fine</th>
                <th style={{ padding: 4 }}>Why Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {liveLogs.map((log, i) => {
                const isViol = log.is_violation || (log.type !== 'ANPR_DETECT' && log.type !== 'VEHICLE' && log.type !== 'CAR' && log.type !== 'MOTORCYCLE' && log.type !== 'BUS' && log.type !== 'TRUCK')
                const isAnpr = log.type === 'ANPR_DETECT'
                const st = (log.status || '').toLowerCase()
                const isScanning = log.plate === 'SCANNING...'
                const hasPlate = log.plate && log.plate !== '-' && log.plate !== 'UNREAD'

                return (
                  <tr key={i} style={{ borderBottom: '1px solid #1a2236' }}>
                    <td style={{ padding: '4px 6px' }}>
                      <span
                        style={{
                          background: isAnpr ? 'rgba(46,213,115,0.15)' : isViol ? 'rgba(255,71,87,0.15)' : 'rgba(0,210,255,0.15)',
                          color: isAnpr ? '#2ed573' : isViol ? '#ff4757' : '#00d2ff',
                          border: `1px solid ${isAnpr ? 'rgba(46,213,115,0.3)' : isViol ? 'rgba(255,71,87,0.3)' : 'rgba(0,210,255,0.3)'}`,
                          padding: '1px 6px',
                          borderRadius: 4,
                          fontWeight: 700,
                          fontSize: 10,
                        }}
                      >
                        {isAnpr ? 'ANPR READ' : log.type}
                      </span>
                    </td>
                    <td style={{ padding: '4px 6px', fontFamily: 'JetBrains Mono', color: '#cbd5e0' }}>#{log.track_id}</td>
                    <td style={{ padding: '4px 6px' }}>
                      {hasPlate ? (
                        <span
                          style={{
                            fontFamily: 'JetBrains Mono',
                            color: isScanning ? '#ffa502' : '#2ed573',
                            fontWeight: isScanning ? 400 : 700,
                            fontStyle: isScanning ? 'italic' : 'normal',
                            background: isScanning ? 'transparent' : 'rgba(46,213,115,0.08)',
                            padding: isScanning ? '0' : '1px 4px',
                            borderRadius: 3,
                          }}
                        >
                          {log.plate}
                        </span>
                      ) : (
                        <span style={{ color: '#718096' }}>-</span>
                      )}
                    </td>
                    <td style={{ padding: '4px 6px', color: '#a0aec0' }}>{log.conf}</td>
                    <td style={{ padding: '4px 6px' }}>
                      <span
                        style={{
                          background:
                            st === 'issued'
                              ? 'rgba(46,213,115,0.2)'
                              : st === 'review'
                              ? 'rgba(255,165,2,0.2)'
                              : st === 'detected' || st === 'verified'
                              ? 'rgba(0,210,255,0.2)'
                              : 'rgba(160,174,192,0.15)',
                          color:
                            st === 'issued'
                              ? '#2ed573'
                              : st === 'review'
                              ? '#ffa502'
                              : st === 'detected' || st === 'verified'
                              ? '#00d2ff'
                              : '#a0aec0',
                          padding: '1px 6px',
                          borderRadius: 4,
                          fontWeight: st === 'tracking' ? 400 : 700,
                          fontSize: 10,
                        }}
                      >
                        {st === 'detected' || st === 'verified' ? 'VERIFIED' : log.status ? log.status.toUpperCase() : 'DETECTED'}
                      </span>
                    </td>
                    <td style={{ padding: '4px 6px', color: log.fine && log.fine !== '-' ? '#ff4757' : '#718096', fontWeight: log.fine && log.fine !== '-' ? 700 : 400 }}>
                      {log.fine}
                    </td>
                    <td style={{ padding: '4px 6px', color: '#cbd5e0', fontSize: 10.5 }}>{log.reasons}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Bottom toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 10px 8px',
        }}
      >
        {/* Grid switcher */}
        <div
          style={{
            display: 'flex',
            gap: 4,
            background: '#161c28',
            border: '1px solid #262f40',
            borderRadius: 6,
            padding: 3,
          }}
        >
          {GRID_MODES.map((m) => (
            <button
              key={m}
              onClick={() => setGridMode(m)}
              style={{
                padding: '4px 12px',
                background: gridMode === m ? '#00d2ff' : 'none',
                border: 'none',
                borderRadius: 4,
                color: gridMode === m ? '#000' : '#a0aec0',
                fontSize: 11,
                fontWeight: gridMode === m ? 700 : 400,
                cursor: 'pointer',
                fontFamily: 'Inter, sans-serif',
                transition: 'all 0.15s',
                letterSpacing: '0.04em',
              }}
            >
              {m}
            </button>
          ))}
        </div>

        {/* Center: camera label */}
        <div style={{ fontSize: 11, color: '#4a5a72', fontFamily: 'Inter, sans-serif' }}>
          Current Site — Exit (Camera 1)
        </div>

        {/* Right: aspect + fullscreen */}
        <div style={{ display: 'flex', gap: 6 }}>
          <ToolbarBtn label="16:9" />
          <ToolbarBtn label="⤢" onClick={() => setFullscreen(!fullscreen)} />
        </div>
      </div>
    </div>
  )
}

function VideoBackground() {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: `
          radial-gradient(ellipse at 50% 100%, #1a2a1a 0%, transparent 60%),
          linear-gradient(to bottom, #0a0f14 0%, #111820 40%, #0d1a0d 100%)
        `,
        overflow: 'hidden',
      }}
    >
      {/* Road perspective lines */}
      <svg width="100%" height="100%" viewBox="0 0 800 450" preserveAspectRatio="xMidYMid slice" style={{ position: 'absolute', inset: 0, opacity: 0.5 }}>
        {/* Sky gradient */}
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0a1520" />
            <stop offset="50%" stopColor="#111f2e" />
            <stop offset="100%" stopColor="#0d1a12" />
          </linearGradient>
          <linearGradient id="road" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1a1a1a" />
            <stop offset="100%" stopColor="#2a2a2a" />
          </linearGradient>
          <linearGradient id="glow" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#00d2ff" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#00d2ff" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Background */}
        <rect width="800" height="450" fill="url(#sky)" />

        {/* Horizon glow */}
        <ellipse cx="400" cy="230" rx="300" ry="40" fill="#00d2ff" opacity="0.04" />

        {/* Road surface */}
        <polygon points="160,450 640,450 520,230 280,230" fill="url(#road)" />

        {/* Road lane dividers */}
        <line x1="400" y1="450" x2="400" y2="230" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="20,16" opacity="0.15" />
        <line x1="320" y1="450" x2="380" y2="230" stroke="#ffffff" strokeWidth="1" strokeDasharray="15,12" opacity="0.08" />
        <line x1="480" y1="450" x2="420" y2="230" stroke="#ffffff" strokeWidth="1" strokeDasharray="15,12" opacity="0.08" />

        {/* Road edges */}
        <line x1="160" y1="450" x2="280" y2="230" stroke="#ffa502" strokeWidth="2" opacity="0.3" />
        <line x1="640" y1="450" x2="520" y2="230" stroke="#ffa502" strokeWidth="2" opacity="0.3" />

        {/* Vehicle silhouettes */}
        <g transform="translate(340, 310)" opacity="0.6">
          <rect x="0" y="20" width="90" height="35" rx="4" fill="#1e2e1e" />
          <rect x="15" y="8" width="60" height="25" rx="4" fill="#1a281a" />
          <circle cx="18" cy="55" r="10" fill="#111" />
          <circle cx="72" cy="55" r="10" fill="#111" />
          {/* headlights */}
          <ellipse cx="85" cy="37" rx="6" ry="5" fill="#ffa502" opacity="0.7" />
          <ellipse cx="85" cy="37" rx="20" ry="8" fill="#ffa502" opacity="0.1" />
        </g>

        <g transform="translate(210, 330) scale(0.7)" opacity="0.45">
          <rect x="0" y="20" width="90" height="35" rx="4" fill="#1e1e2e" />
          <rect x="15" y="8" width="60" height="25" rx="4" fill="#181828" />
          <circle cx="18" cy="55" r="10" fill="#111" />
          <circle cx="72" cy="55" r="10" fill="#111" />
          <ellipse cx="5" cy="37" rx="5" ry="4" fill="#ff4757" opacity="0.5" />
        </g>

        {/* Street lamp posts */}
        <line x1="155" y1="230" x2="145" y2="430" stroke="#2a3a4a" strokeWidth="2" opacity="0.6" />
        <ellipse cx="155" cy="230" rx="30" ry="8" fill="#ffffaa" opacity="0.06" />
        <line x1="645" y1="230" x2="655" y2="430" stroke="#2a3a4a" strokeWidth="2" opacity="0.6" />
        <ellipse cx="645" cy="230" rx="30" ry="8" fill="#ffffaa" opacity="0.06" />

        {/* ANPR detection box */}
        <rect x="338" y="308" width="94" height="65" fill="none" stroke="#00d2ff" strokeWidth="1.5" strokeDasharray="8,4" opacity="0.8" />
        <rect x="338" y="295" width="60" height="14" rx="2" fill="#00d2ff" />
        <text x="341" y="306" fontSize="9" fill="#000" fontFamily="Inter" fontWeight="700">DETECTED</text>

        {/* Scan line effect */}
        <rect x="0" y="0" width="800" height="2" fill="url(#glow)" opacity="0.4">
          <animateTransform attributeName="transform" type="translate" from="0,0" to="0,450" dur="3s" repeatCount="indefinite" />
        </rect>
      </svg>

      {/* Scanline texture overlay */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.08) 2px, rgba(0,0,0,0.08) 4px)',
          pointerEvents: 'none',
        }}
      />

      {/* Vignette */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.6) 100%)',
          pointerEvents: 'none',
        }}
      />

      {/* Corner brackets — spatial depth marker */}
      {[
        { top: 8, left: 8 },
        { top: 8, right: 8 },
        { bottom: 8, left: 8 },
        { bottom: 8, right: 8 },
      ].map((pos, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            ...pos,
            width: 20,
            height: 20,
            borderTop: i < 2 ? '1.5px solid #00d2ff66' : 'none',
            borderBottom: i >= 2 ? '1.5px solid #00d2ff66' : 'none',
            borderLeft: i % 2 === 0 ? '1.5px solid #00d2ff66' : 'none',
            borderRight: i % 2 !== 0 ? '1.5px solid #00d2ff66' : 'none',
          }}
        />
      ))}
    </div>
  )
}

function LiveIndicator() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: '#ff4757',
          boxShadow: '0 0 8px #ff4757',
          animation: 'pulse 1.4s ease-in-out infinite',
        }}
      />
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: '#ff4757',
          letterSpacing: '0.12em',
          fontFamily: 'Inter, sans-serif',
        }}
      >
        LIVE
      </span>
    </div>
  )
}

function DetectionBox({ plate, confidence }: { plate: string; confidence: number }) {
  return (
    <div
      style={{
        background: 'rgba(0,0,0,0.75)',
        border: '1px solid #00d2ff55',
        borderRadius: 6,
        padding: '6px 10px',
        backdropFilter: 'blur(4px)',
        boxShadow: '0 0 12px rgba(0,210,255,0.15)',
      }}
    >
      <div style={{ fontSize: 9, color: '#00d2ff', fontWeight: 700, letterSpacing: '0.1em', marginBottom: 3 }}>
        ANPR DETECT
      </div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 700, color: '#fff', letterSpacing: '0.12em' }}>
        {plate}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
        <span style={{ fontSize: 9.5, color: '#a0aec0', fontFamily: 'Inter, sans-serif' }}>Confidence</span>
        <span style={{ fontSize: 9.5, color: '#2ed573', fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 }}>
          {confidence}%
        </span>
      </div>
    </div>
  )
}

function SpeedBadge({ label, color, small }: { label: string; color: string; small?: boolean }) {
  return (
    <div
      style={{
        padding: small ? '3px 10px' : '5px 14px',
        background: `${color}22`,
        border: `1px solid ${color}66`,
        borderRadius: 4,
        color: color,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: small ? 11 : 14,
        fontWeight: 700,
        letterSpacing: '0.08em',
        boxShadow: `0 0 10px ${color}33`,
      }}
    >
      {label}
    </div>
  )
}

function GridOverlay({ mode }: { mode: GridMode }) {
  const count = mode === '2×2' ? 4 : 9
  const cols = mode === '2×2' ? 2 : 3

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: 2,
        padding: 2,
        background: '#0d1117',
        zIndex: 5,
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            background: i === 0 ? '#111820' : '#0a0f14',
            border: i === 0 ? '1px solid #00d2ff44' : '1px solid #262f40',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {i > 0 && (
            <span style={{ fontSize: 10, color: '#262f40', fontFamily: 'Inter, sans-serif' }}>
              CAM {i + 1}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

function VideoToolBtn({
  children,
  title,
  active,
  onClick,
}: {
  children: React.ReactNode
  title?: string
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 28,
        height: 28,
        background: active ? 'rgba(255,71,87,0.2)' : 'rgba(0,0,0,0.4)',
        border: `1px solid ${active ? '#ff4757' : '#262f4066'}`,
        borderRadius: 5,
        color: active ? '#ff4757' : '#a0aec0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        transition: 'all 0.15s',
        backdropFilter: 'blur(4px)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(0,210,255,0.15)'
        e.currentTarget.style.color = '#00d2ff'
        e.currentTarget.style.borderColor = '#00d2ff44'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = active ? 'rgba(255,71,87,0.2)' : 'rgba(0,0,0,0.4)'
        e.currentTarget.style.color = active ? '#ff4757' : '#a0aec0'
        e.currentTarget.style.borderColor = active ? '#ff4757' : '#262f4066'
      }}
    >
      {children}
    </button>
  )
}

function ToolbarBtn({ label, onClick }: { label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '4px 12px',
        background: '#161c28',
        border: '1px solid #262f40',
        borderRadius: 5,
        color: '#a0aec0',
        fontSize: 11,
        cursor: 'pointer',
        fontFamily: 'Inter, sans-serif',
        transition: 'all 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#00d2ff55'
        e.currentTarget.style.color = '#00d2ff'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#262f40'
        e.currentTarget.style.color = '#a0aec0'
      }}
    >
      {label}
    </button>
  )
}
