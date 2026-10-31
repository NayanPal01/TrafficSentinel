import { useState } from 'react'

const CAMERAS = [
  { id: 'cam1', name: 'CAM-01 (Park Street Junction)', label: 'Camera 1', ip: '192.168.100.158', status: 'online' },
  { id: 'cam2', name: 'CAM-02 (Howrah Approach)', label: 'Camera 2', ip: '192.168.100.158', status: 'online' },
  { id: 'cam3', name: 'CAM-03 (Salt Lake Sector V)', label: 'Camera 3', ip: '192.168.100.158', status: 'idle' },
  { id: 'cam4', name: 'CAM-04 (Airport Expressway)', label: 'Camera 4', ip: '192.168.100.158', status: 'online' },
]

const RULES = [
  { id: 'OVERSPEEDING', label: 'Overspeeding' },
  { id: 'RED_LIGHT', label: 'Red Light Crossing' },
  { id: 'NO_HELMET', label: 'Helmet Classification' },
  { id: 'TRIPLE_RIDING', label: 'Triple Riding' },
  { id: 'WRONG_WAY', label: 'Wrong-Way Driving' },
  { id: 'ILLEGAL_PARKING', label: 'Illegal Parking' },
]

export default function LeftSidebar() {
  const [resourceTab, setResourceTab] = useState<'Resources' | 'Favorites'>('Resources')
  const [selectedCam, setSelectedCam] = useState('cam1')
  const [siteExpanded, setSiteExpanded] = useState(true)
  const [ipExpanded, setIpExpanded] = useState(true)
  const [rulesOpen, setRulesOpen] = useState(true)
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [search, setSearch] = useState('')

  const [sourceKind, setSourceKind] = useState<'upload' | 'webcam' | 'rtsp'>('upload')
  const [webcamIdx, setWebcamIdx] = useState(0)
  const [rtspUrl, setRtspUrl] = useState('rtsp://user:pass@192.168.1.10:554/stream')

  const [speedLimit, setSpeedLimit] = useState(60)
  const [autoConf, setAutoConf] = useState(0.65)
  const [enabledRules, setEnabledRules] = useState<Record<string, boolean>>({
    OVERSPEEDING: true,
    RED_LIGHT: true,
    NO_HELMET: true,
    TRIPLE_RIDING: true,
    WRONG_WAY: true,
    ILLEGAL_PARKING: true,
  })

  const [botToken, setBotToken] = useState('8850261046:AAG1gi0rcDDDPe4ny2YIo5fVXv65MDsxWQE')
  const [chatId, setChatId] = useState('5023326653')
  const [alertMsg, setAlertMsg] = useState('')

  const updateBackendSettings = (newSettings: any) => {
    fetch('http://localhost:8765/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSettings),
    }).catch(() => {})
  }

  const toggleRule = (ruleId: string) => {
    const updated = { ...enabledRules, [ruleId]: !enabledRules[ruleId] }
    setEnabledRules(updated)
    updateBackendSettings({ enabled_rules: updated })
  }

  const handleSendTestAlert = () => {
    setAlertMsg('Sending...')
    fetch('http://localhost:8765/api/alerts/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bot_token: botToken, chat_id: chatId }),
    })
      .then((res) => res.json())
      .then((data) => setAlertMsg(data.message || 'Alert sent!'))
      .catch(() => setAlertMsg('Failed to send alert.'))
  }

  const filtered = CAMERAS.filter(
    (c) =>
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.label.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <aside
      style={{
        width: 260,
        height: '100%',
        background: '#161c28',
        borderRight: '1px solid #262f40',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Search */}
      <div style={{ padding: '10px 12px 8px', borderBottom: '1px solid #262f40' }}>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search camera or node..."
          style={{
            width: '100%',
            background: '#0d1117',
            border: '1px solid #262f40',
            borderRadius: 6,
            color: '#fff',
            fontSize: 11.5,
            padding: '6px 8px',
            outline: 'none',
          }}
        />
      </div>

      {/* Video Source Upload / CCTV / Webcam Selector (Restored Streamlit feature) */}
      <div style={{ borderBottom: '1px solid #262f40', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#00d2ff' }}>📹 Video Source Selector</div>
        
        {/* Source Kind Radio Buttons */}
        <div style={{ display: 'flex', gap: 4, background: '#0d1117', padding: 2, borderRadius: 4, border: '1px solid #262f40' }}>
          {(['upload', 'webcam', 'rtsp'] as const).map((kind) => (
            <button
              key={kind}
              onClick={() => {
                setSourceKind(kind)
                if (kind === 'upload') {
                  fetch('http://localhost:8765/api/source', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ kind: 'upload', source: '_upload.mp4' }),
                  }).catch(() => {})
                }
              }}
              style={{
                flex: 1,
                padding: '4px 0',
                background: sourceKind === kind ? '#00d2ff' : 'none',
                color: sourceKind === kind ? '#000' : '#a0aec0',
                border: 'none',
                borderRadius: 3,
                fontSize: 10,
                fontWeight: 700,
                cursor: 'pointer',
                textTransform: 'uppercase',
              }}
            >
              {kind}
            </button>
          ))}
        </div>

        {/* Upload File Input */}
        {sourceKind === 'upload' && (
          <div style={{ position: 'relative' }}>
            <label
              htmlFor="file-upload-input"
              style={{
                display: 'block',
                width: '100%',
                padding: '8px 10px',
                background: '#1a2236',
                border: '2px dashed #00d2ff',
                borderRadius: 6,
                color: '#00d2ff',
                fontSize: 11,
                fontWeight: 700,
                textAlign: 'center',
                cursor: 'pointer',
                boxSizing: 'border-box',
              }}
            >
              📤 Click to Select Video File...
            </label>
            <input
              id="file-upload-input"
              type="file"
              accept="video/*"
              style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', opacity: 0, cursor: 'pointer' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                const formData = new FormData()
                formData.append('file', file)
                fetch('http://localhost:8765/api/upload-video', {
                  method: 'POST',
                  body: formData,
                })
                  .then((res) => res.json())
                  .then((data) => alert(`Uploaded & Started: ${file.name}`))
                  .catch(() => alert('Upload failed.'))
              }}
            />
          </div>
        )}

        {/* Webcam Index Input */}
        {sourceKind === 'webcam' && (
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type="number"
              value={webcamIdx}
              onChange={(e) => setWebcamIdx(Number(e.target.value))}
              style={{ width: 50, background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 11, padding: '4px' }}
              placeholder="0"
            />
            <button
              onClick={() => {
                fetch('http://localhost:8765/api/source', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ kind: 'webcam', source: webcamIdx.toString() }),
                }).catch(() => {})
              }}
              style={{ flex: 1, background: '#2ed573', border: 'none', color: '#000', fontWeight: 700, fontSize: 11, borderRadius: 4, cursor: 'pointer' }}
            >
              Connect Webcam
            </button>
          </div>
        )}

        {/* RTSP / CCTV URL Input */}
        {sourceKind === 'rtsp' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <input
              type="text"
              value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
              style={{ width: '100%', background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 10, padding: '4px' }}
              placeholder="rtsp://user:pass@192.168.1.10:554/stream"
            />
            <button
              onClick={() => {
                fetch('http://localhost:8765/api/source', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ kind: 'rtsp', source: rtspUrl }),
                }).catch(() => {})
              }}
              style={{ width: '100%', background: '#00d2ff', border: 'none', color: '#000', fontWeight: 700, fontSize: 11, borderRadius: 4, cursor: 'pointer', padding: '4px' }}
            >
              Connect CCTV Stream
            </button>
          </div>
        )}
      </div>


      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid #262f40' }}>
        {(['Resources', 'Favorites'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setResourceTab(t)}
            style={{
              flex: 1,
              padding: '7px 0',
              background: 'none',
              border: 'none',
              borderBottom: resourceTab === t ? '2px solid #00d2ff' : '2px solid transparent',
              color: resourceTab === t ? '#00d2ff' : '#a0aec0',
              fontSize: 11.5,
              fontWeight: resourceTab === t ? 600 : 400,
              cursor: 'pointer',
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Tree & Rules Scrollable Container */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        <TreeNode
          label="Current Site"
          badge="1/1"
          expanded={siteExpanded}
          onToggle={() => setSiteExpanded(!siteExpanded)}
        />
        {siteExpanded && (
          filtered.map((cam) => (
            <div
              key={cam.id}
              onClick={() => {
                setSelectedCam(cam.id)
                updateBackendSettings({ camera_preset: cam.name })
              }}
              style={{
                padding: '6px 12px 6px 24px',
                fontSize: 11,
                color: selectedCam === cam.id ? '#00d2ff' : '#a0aec0',
                background: selectedCam === cam.id ? 'rgba(0, 210, 255, 0.15)' : 'none',
                cursor: 'pointer',
              }}
            >
              📷 {cam.name}
            </div>
          ))
        )}

        {/* AI Rule Controls */}
        <div style={{ borderTop: '1px solid #262f40', marginTop: 12, paddingTop: 8 }}>
          <div
            onClick={() => setRulesOpen(!rulesOpen)}
            style={{ padding: '6px 12px', fontSize: 11, fontWeight: 700, color: '#00d2ff', cursor: 'pointer' }}
          >
            ⚙️ Active Enforcement Rules
          </div>

          {rulesOpen && (
            <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div>
                <label style={{ fontSize: 10.5, color: '#a0aec0' }}>Speed Limit (km/h): </label>
                <input
                  type="number"
                  value={speedLimit}
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    setSpeedLimit(val)
                    updateBackendSettings({ speed_limit: val })
                  }}
                  style={{ width: 60, background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 11, padding: '2px 4px' }}
                />
              </div>

              <div>
                <label style={{ fontSize: 10.5, color: '#a0aec0' }}>Auto-Issue Conf: {autoConf}</label>
                <input
                  type="range"
                  min={0.5}
                  max={0.99}
                  step={0.05}
                  value={autoConf}
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    setAutoConf(val)
                    updateBackendSettings({ auto_issue_conf: val })
                  }}
                  style={{ width: '100%' }}
                />
              </div>

              {RULES.map((rule) => (
                <label key={rule.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#e6edf3', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={!!enabledRules[rule.id]}
                    onChange={() => toggleRule(rule.id)}
                    style={{ accentColor: '#00d2ff' }}
                  />
                  {rule.label}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Telegram Alerts Section */}
        <div style={{ borderTop: '1px solid #262f40', marginTop: 8, paddingTop: 8 }}>
          <div
            onClick={() => setAlertsOpen(!alertsOpen)}
            style={{ padding: '6px 12px', fontSize: 11, fontWeight: 700, color: '#ff4757', cursor: 'pointer' }}
          >
            📱 Telegram Police Alerts
          </div>

          {alertsOpen && (
            <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <label style={{ fontSize: 10, color: '#a0aec0' }}>Bot Token</label>
                <input
                  type="password"
                  value={botToken}
                  onChange={(e) => setBotToken(e.target.value)}
                  style={{ width: '100%', background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 10, padding: 4 }}
                />
              </div>

              <div>
                <label style={{ fontSize: 10, color: '#a0aec0' }}>Chat ID</label>
                <input
                  type="text"
                  value={chatId}
                  onChange={(e) => setChatId(e.target.value)}
                  style={{ width: '100%', background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 10, padding: 4 }}
                />
              </div>

              <button
                onClick={handleSendTestAlert}
                style={{
                  background: '#ff4757',
                  border: 'none',
                  borderRadius: 4,
                  color: '#fff',
                  fontSize: 11,
                  padding: '6px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Send Test Alert
              </button>
              {alertMsg && <div style={{ fontSize: 10, color: '#2ed573' }}>{alertMsg}</div>}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function TreeNode({ label, badge, expanded, onToggle }: { label: string; badge?: string; expanded: boolean; onToggle: () => void }) {
  return (
    <div
      onClick={onToggle}
      style={{
        padding: '6px 12px',
        display: 'flex',
        justify: 'space-between',
        fontSize: 11.5,
        fontWeight: 600,
        color: '#fff',
        cursor: 'pointer',
      }}
    >
      <span>{expanded ? '▼' : '▶'} {label}</span>
      {badge && <span style={{ fontSize: 10, color: '#00d2ff' }}>{badge}</span>}
    </div>
  )
}
