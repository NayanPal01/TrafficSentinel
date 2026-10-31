import { useState, useEffect } from 'react'
import TopNav from './components/TopNav'
import LeftSidebar from './components/LeftSidebar'
import VideoViewport from './components/VideoViewport'
import RightSidebar from './components/RightSidebar'

export default function App() {
  const [activeTab, setActiveTab] = useState('Live View')
  const [reviewItems, setReviewItems] = useState<any[]>([])
  const [analyticsData, setAnalyticsData] = useState<any>(null)
  const [calibrationData, setCalibrationData] = useState<any>(null)
  const [searchPlate, setSearchPlate] = useState('')
  const [traceData, setTraceData] = useState<any>(null)
  const [actionMsg, setActionMsg] = useState('')

  // Fetch Review Queue items
  const fetchReviewQueue = () => {
    fetch('http://localhost:8765/api/review')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) setReviewItems(data)
      })
      .catch(() => {})
  }

  // Fetch Analytics data
  const fetchAnalytics = () => {
    fetch('http://localhost:8765/api/analytics')
      .then((res) => res.json())
      .then((data) => setAnalyticsData(data))
      .catch(() => {})
  }

  // Fetch Calibration data
  const fetchCalibration = () => {
    fetch('http://localhost:8765/api/calibration')
      .then((res) => res.json())
      .then((data) => setCalibrationData(data))
      .catch(() => {})
  }

  useEffect(() => {
    if (activeTab === 'Review Queue') fetchReviewQueue()
    if (activeTab === 'Analytics') fetchAnalytics()
    if (activeTab === 'Calibration Status') fetchCalibration()
  }, [activeTab])

  // Handle Review Actions (Issue Challan or Dismiss)
  const handleReviewAction = (violationId: number, action: 'issue' | 'dismiss', verifiedPlate: string) => {
    fetch('http://localhost:8765/api/review/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ violation_id: violationId, action, verified_plate: verifiedPlate }),
    })
      .then((res) => res.json())
      .then(() => {
        setActionMsg(`Violation #${violationId} marked as ${action === 'issue' ? 'Issued' : 'Dismissed'}`)
        fetchReviewQueue()
      })
      .catch(() => {})
  }

  // Clear All Logs
  const handleClearAll = () => {
    if (window.confirm('Are you sure you want to delete all violation logs and evidence files?')) {
      fetch('http://localhost:8765/api/review/clear-all', { method: 'POST' })
        .then(() => {
          setActionMsg('All logs and evidence cleared.')
          fetchReviewQueue()
        })
        .catch(() => {})
    }
  }

  // Trace Vehicle Plate
  const handleTracePlate = (plateToSearch: string) => {
    if (!plateToSearch) return
    fetch(`http://localhost:8765/api/anpr/trace?plate=${encodeURIComponent(plateToSearch)}`)
      .then((res) => res.json())
      .then((data) => setTraceData(data))
      .catch(() => {})
  }

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: '#0d1117',
        fontFamily: 'Inter, sans-serif',
        overflow: 'hidden',
      }}
    >
      <TopNav activeTab={activeTab} onTabChange={setActiveTab} />

      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
          minHeight: 0,
        }}
      >
        {activeTab === 'Live View' && (
          <>
            <LeftSidebar />
            <VideoViewport />
            <RightSidebar />
          </>
        )}

        {/* REVIEW QUEUE TAB */}
        {activeTab === 'Review Queue' && (
          <div style={{ flex: 1, padding: 24, overflowY: 'auto', background: '#0d1117', color: '#fff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h2 style={{ fontSize: 20, color: '#00d2ff' }}>📋 Officer Review Queue</h2>
                <p style={{ fontSize: 12, color: '#a0aec0' }}>
                  Violations awaiting human officer confirmation or dismissal before issuing challans.
                </p>
              </div>
              <button
                onClick={handleClearAll}
                style={{
                  background: 'rgba(255,71,87,0.2)',
                  border: '1px solid #ff4757',
                  color: '#ff4757',
                  padding: '8px 16px',
                  borderRadius: 6,
                  fontWeight: 600,
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                🗑️ Clear All Logs & Evidence
              </button>
            </div>

            {actionMsg && (
              <div style={{ background: '#161c28', border: '1px solid #00d2ff', color: '#00d2ff', padding: '8px 12px', borderRadius: 6, marginBottom: 16, fontSize: 12 }}>
                {actionMsg}
              </div>
            )}

            {reviewItems.length === 0 ? (
              <div style={{ background: '#161c28', border: '1px solid #262f40', padding: 24, borderRadius: 8, textAlign: 'center', color: '#a0aec0', fontSize: 13 }}>
                ✅ No violations currently awaiting review.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {reviewItems.map((item) => (
                  <ReviewCard key={item.violation_id} item={item} onAction={handleReviewAction} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ANALYTICS TAB */}
        {activeTab === 'Analytics' && (
          <div style={{ flex: 1, padding: 24, overflowY: 'auto', background: '#0d1117', color: '#fff' }}>
            <h2 style={{ fontSize: 20, marginBottom: 16, color: '#00d2ff' }}>📊 Analytics & Fine Revenue</h2>
            
            {analyticsData && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
                  <StatCard label="Total Detections" value={analyticsData.stats?.total?.toString() || '0'} color="#00d2ff" />
                  <StatCard label="Challans Issued" value={analyticsData.stats?.issued?.toString() || '0'} color="#2ed573" />
                  <StatCard label="Awaiting Review" value={analyticsData.stats?.review?.toString() || '0'} color="#ffa502" />
                  <StatCard label="Total Fines Issued" value={`₹ ${analyticsData.stats?.fines?.toLocaleString() || 0}`} color="#ff4757" />
                </div>

                <div style={{ background: '#161c28', border: '1px solid #262f40', borderRadius: 8, padding: 20, marginBottom: 20 }}>
                  <h3 style={{ fontSize: 14, marginBottom: 16, color: '#00d2ff' }}>Fine Revenue Breakdown by Violation Type (INR ₹)</h3>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #262f40', color: '#a0aec0' }}>
                        <th style={{ padding: 8 }}>Violation Type</th>
                        <th style={{ padding: 8 }}>Count</th>
                        <th style={{ padding: 8 }}>Fine per Item (INR)</th>
                        <th style={{ padding: 8 }}>Total Fines (INR)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(analyticsData.fine_breakdown || {}).map(([type, d]: [string, any]) => (
                        <tr key={type} style={{ borderBottom: '1px solid #1a2236' }}>
                          <td style={{ padding: 8, color: '#ff4757', fontWeight: 600 }}>{type}</td>
                          <td style={{ padding: 8 }}>{d.count}</td>
                          <td style={{ padding: 8 }}>₹ {d.fine_per_item}</td>
                          <td style={{ padding: 8, color: '#2ed573', fontWeight: 700 }}>₹ {d.total_fine.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}

        {/* ANPR TRACE TAB */}
        {activeTab === 'ANPR Trace' && (
          <div style={{ flex: 1, padding: 24, overflowY: 'auto', background: '#0d1117', color: '#fff' }}>
            <h2 style={{ fontSize: 20, marginBottom: 16, color: '#00d2ff' }}>🚘 Multi-Camera Vehicle Trajectory</h2>
            
            <div style={{ marginBottom: 16, display: 'flex', gap: 10 }}>
              <input
                type="text"
                value={searchPlate}
                onChange={(e) => setSearchPlate(e.target.value)}
                placeholder="Enter plate number (e.g. MH12AB1234)..."
                style={{
                  width: 320,
                  padding: '8px 12px',
                  background: '#161c28',
                  border: '1px solid #262f40',
                  borderRadius: 6,
                  color: '#fff',
                  outline: 'none',
                  fontSize: 13,
                }}
              />
              <button
                onClick={() => handleTracePlate(searchPlate)}
                style={{
                  background: '#00d2ff',
                  border: 'none',
                  borderRadius: 6,
                  color: '#000',
                  fontWeight: 700,
                  padding: '8px 16px',
                  cursor: 'pointer',
                }}
              >
                Trace Vehicle
              </button>
            </div>

            {traceData && (
              <div style={{ background: '#161c28', border: '1px solid #262f40', borderRadius: 8, padding: 20 }}>
                <h3 style={{ fontSize: 14, color: '#2ed573', marginBottom: 12 }}>
                  📍 Route Checkpoints for `{traceData.plate}` ({traceData.total_checkpoints} Sightings)
                </h3>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #262f40', color: '#00d2ff' }}>
                      <th style={{ padding: 8 }}>Camera Checkpoint</th>
                      <th style={{ padding: 8 }}>Latitude</th>
                      <th style={{ padding: 8 }}>Longitude</th>
                      <th style={{ padding: 8 }}>Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traceData.sightings.map((s: any, i: number) => (
                      <tr key={i} style={{ borderBottom: '1px solid #1a2236' }}>
                        <td style={{ padding: 8 }}>📷 {s.camera_id}</td>
                        <td style={{ padding: 8 }}>{s.latitude}</td>
                        <td style={{ padding: 8 }}>{s.longitude}</td>
                        <td style={{ padding: 8, color: '#a0aec0' }}>{s.ts ? new Date(s.ts * 1000).toLocaleString() : 'N/A'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* CALIBRATION STATUS TAB */}
        {(activeTab === 'Calibration Status' || activeTab === 'Device' || activeTab === 'Playback') && (
          <div style={{ flex: 1, padding: 24, overflowY: 'auto', background: '#0d1117', color: '#fff' }}>
            <h2 style={{ fontSize: 20, marginBottom: 16, color: '#00d2ff' }}>📐 Spatial Calibration & Hardware Status</h2>
            
            {calibrationData && (
              <div style={{ background: '#161c28', border: '1px solid #262f40', borderRadius: 8, padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
                <CalibCheck name="Homography (Ground Plane)" ok={calibrationData.homography} desc="Required for speed & wrong-way calculation." />
                <CalibCheck name="Stop Line Crossing" ok={calibrationData.stop_line} desc="Required for red-light violation detection." />
                <CalibCheck name="Lane Direction Vectors" ok={calibrationData.lane_direction} desc="Required for wrong-way detection." />
                <CalibCheck name="No-Parking Zones" ok={calibrationData.no_parking_zones} desc="Required for illegal parking dwell calculation." />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function ReviewCard({ item, onAction }: { item: any; onAction: (id: number, act: 'issue' | 'dismiss', p: string) => void }) {
  const [plate, setPlate] = useState(item.plate_number || '')

  return (
    <div style={{ background: '#161c28', border: '1px solid #262f40', borderRadius: 8, padding: 16, display: 'flex', gap: 16 }}>
      {/* Media column */}
      <div style={{ width: 220, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {item.evidence_path && (
          <img src={`http://localhost:8765/${item.evidence_path}`} alt="Evidence" style={{ width: '100%', borderRadius: 6, border: '1px solid #262f40' }} />
        )}
        {item.clip_path && (
          <video controls src={`http://localhost:8765/${item.clip_path}`} style={{ width: '100%', borderRadius: 6 }} />
        )}
      </div>

      {/* Details column */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#ff4757' }}>
          {item.violation_type} <span style={{ fontSize: 12, color: '#a0aec0' }}>· Track #{item.track_id}</span>
        </div>
        <div style={{ fontSize: 12, color: '#a0aec0' }}>
          Fine: <strong style={{ color: '#2ed573' }}>₹ {item.fine_amount}</strong> | Confidence: <strong style={{ color: '#00d2ff' }}>{item.confidence?.toFixed(2)}</strong>
        </div>

        <div>
          <label style={{ fontSize: 11, color: '#a0aec0' }}>Verified License Plate Number: </label>
          <input
            type="text"
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            style={{ padding: '4px 8px', background: '#0d1117', border: '1px solid #262f40', color: '#fff', fontSize: 12, borderRadius: 4, marginLeft: 8 }}
          />
        </div>

        <div style={{ fontSize: 11, color: '#a0aec0' }}>
          <strong>Reasoning Chain:</strong>
          <ul style={{ paddingLeft: 16, marginTop: 4 }}>
            {(item.reasons || '').split(' | ').map((r: string, idx: number) => r && <li key={idx}>{r}</li>)}
          </ul>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 'auto', paddingTop: 8 }}>
          <button
            onClick={() => onAction(item.violation_id, 'issue', plate)}
            style={{ background: '#2ed573', border: 'none', color: '#000', fontWeight: 700, padding: '6px 16px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
          >
            Issue Challan
          </button>
          <button
            onClick={() => onAction(item.violation_id, 'dismiss', plate)}
            style={{ background: 'none', border: '1px solid #ff4757', color: '#ff4757', padding: '6px 16px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
          >
            Dismiss (False Positive)
          </button>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: '#161c28', border: '1px solid #262f40', borderRadius: 8, padding: 16 }}>
      <div style={{ fontSize: 11, color: '#a0aec0', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

function CalibCheck({ name, ok, desc }: { name: string; ok: boolean; desc: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ fontSize: 18 }}>{ok ? '✅' : '⛔'}</div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: ok ? '#2ed573' : '#ff4757' }}>{name}</div>
        <div style={{ fontSize: 11, color: '#a0aec0' }}>{desc}</div>
      </div>
    </div>
  )
}
