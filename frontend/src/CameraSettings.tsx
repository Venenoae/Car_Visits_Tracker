import { useEffect, useState } from 'react';
import { ArrowLeft, Plus, RefreshCw, Trash2, Camera as CameraIcon, Wifi, WifiOff, ExternalLink, HardDrive, CheckCircle } from 'lucide-react';

interface CameraConfig {
  id: string;
  name: string;
  zone: string;
  host: string;
  port: number;
}

interface StorageStats {
  total_files: number;
  total_size_mb: number;
  old_files: number;
  old_size_mb: number;
  retention_days: number;
  cutoff_date: string;
}

const BACKEND_HOST = typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1';
const API_BASE = `http://${BACKEND_HOST}:8000/api`;

const STORAGE_KEY = 'camera_settings';
const DEFAULT_CAMERAS: CameraConfig[] = [
  { id: 'cam-zone-a', name: 'Gate Camera', zone: 'Zone A', host: '192.168.0.240', port: 8080 },
];

function loadCameras(): CameraConfig[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch { /* fall through to defaults */ }
  return DEFAULT_CAMERAS;
}

type Status = 'connecting' | 'online' | 'offline';

export default function CameraSettings({ onBack }: { onBack: () => void }) {
  const [cameras, setCameras] = useState<CameraConfig[]>(loadCameras);
  const [selectedId, setSelectedId] = useState<string>(() => loadCameras()[0].id);
  const [status, setStatus] = useState<Status>('connecting');
  const [streamKey, setStreamKey] = useState(0);
  const [frameSize, setFrameSize] = useState<string>('');

  const [showCrosshair, setShowCrosshair] = useState(true);
  const [showThirds, setShowThirds] = useState(true);
  const [showLevel, setShowLevel] = useState(false);

  // Storage maintenance state
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [isCleaning, setIsCleaning] = useState(false);
  const [cleanMsg, setCleanMsg] = useState<string | null>(null);

  const fetchStorageStats = async () => {
    const token = localStorage.getItem('token');
    try {
      const res = await fetch(`${API_BASE}/maintenance/storage-stats`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setStorageStats(data);
      }
    } catch (err) {
      console.error('Failed to fetch storage stats:', err);
    }
  };

  useEffect(() => {
    fetchStorageStats();
  }, []);

  const handleManualClean = async () => {
    const token = localStorage.getItem('token');
    setIsCleaning(true);
    setCleanMsg(null);
    try {
      const res = await fetch(`${API_BASE}/maintenance/cleanup-images`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setCleanMsg(`Cleaned ${data.deleted_count} files (${data.freed_mb} MB freed). DB records intact!`);
        await fetchStorageStats();
      }
    } catch (err) {
      setCleanMsg('Cleanup request failed. Check server connection.');
    } finally {
      setIsCleaning(false);
    }
  };


  const selected = cameras.find(c => c.id === selectedId) ?? cameras[0];

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cameras));
  }, [cameras]);

  const reconnect = () => {
    setStatus('connecting');
    setFrameSize('');
    setStreamKey(k => k + 1);
  };

  const updateSelected = (patch: Partial<CameraConfig>) => {
    setCameras(prev => prev.map(c => (c.id === selected.id ? { ...c, ...patch } : c)));
  };

  const addCamera = () => {
    const id = `cam-${Date.now()}`;
    const cam: CameraConfig = { id, name: 'New Camera', zone: 'Zone B', host: '192.168.0.241', port: 8080 };
    setCameras(prev => [...prev, cam]);
    setSelectedId(id);
    setStatus('connecting');
  };

  const removeSelected = () => {
    if (cameras.length <= 1) return;
    const remaining = cameras.filter(c => c.id !== selected.id);
    setCameras(remaining);
    setSelectedId(remaining[0].id);
    setStatus('connecting');
  };

  const baseUrl = `http://${selected.host}:${selected.port}`;
  const streamUrl = `${baseUrl}/stream.mjpg`;

  const statusColor = status === 'online' ? 'var(--success)' : status === 'offline' ? 'var(--danger)' : 'var(--warning)';

  return (
    <div className="app-container">
      <header className="app-header glass-card">
        <div className="brand-section">
          <div className="brand-icon"><CameraIcon size={24} color="#FFFFFF" /></div>
          <div>
            <h1 className="brand-title">Camera Settings</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Mounting &amp; alignment assistant</p>
          </div>
        </div>
        <div className="header-actions">
          <button className="btn btn-outline" onClick={onBack}>
            <ArrowLeft size={16} /> Back to Dashboard
          </button>
        </div>
      </header>

      <div className="cam-layout">
        {/* Left: camera list + config */}
        <aside className="glass-card cam-sidebar">
          <div className="cam-sidebar-title">
            <strong>Cameras</strong>
            <button className="btn btn-outline" onClick={addCamera} aria-label="Add camera" id="add-camera-btn">
              <Plus size={14} /> Add
            </button>
          </div>

          <div className="cam-list">
            {cameras.map(c => (
              <button
                key={c.id}
                className={`cam-list-item ${c.id === selected.id ? 'active' : ''}`}
                onClick={() => { setSelectedId(c.id); setStatus('connecting'); setFrameSize(''); }}
              >
                <span>{c.name}</span>
                <small>{c.zone} · {c.host}</small>
              </button>
            ))}
          </div>

          <div className="cam-form">
            <label className="form-label" htmlFor="cam-name">Name</label>
            <input id="cam-name" className="form-input" value={selected.name}
              onChange={e => updateSelected({ name: e.target.value })} />

            <label className="form-label" htmlFor="cam-zone">Zone</label>
            <select id="cam-zone" className="form-input" value={selected.zone}
              onChange={e => updateSelected({ zone: e.target.value })}>
              <option>Zone A</option>
              <option>Zone B</option>
            </select>

            <label className="form-label" htmlFor="cam-host">Pi IP / Host</label>
            <input id="cam-host" className="form-input" value={selected.host}
              onChange={e => updateSelected({ host: e.target.value.trim() })} />

            <label className="form-label" htmlFor="cam-port">Stream Port</label>
            <input id="cam-port" className="form-input" type="number" value={selected.port}
              onChange={e => updateSelected({ port: Number(e.target.value) || 8080 })} />

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
              <button className="btn btn-primary" onClick={reconnect} id="cam-apply-btn">
                <RefreshCw size={14} /> Apply &amp; Reconnect
              </button>
              <button className="btn btn-outline" onClick={removeSelected}
                disabled={cameras.length <= 1} aria-label="Remove camera">
                <Trash2 size={14} />
              </button>
            </div>
          </div>

          {/* Storage & Image Retention Section */}
          <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--border-light)', paddingTop: '1.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.6rem' }}>
              <strong style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.875rem', color: '#FFFFFF' }}>
                <HardDrive size={16} style={{ color: 'var(--primary)' }} /> Snapshot Retention
              </strong>
              <span style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem', background: 'rgba(56, 189, 248, 0.12)', color: 'var(--primary)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: '4px', fontWeight: 700 }}>
                {storageStats ? `${storageStats.retention_days}-Day Policy` : '2-Day Policy'}
              </span>
            </div>

            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.85rem', lineHeight: 1.45 }}>
              Snapshots older than 2 days are automatically purged to prevent disk saturation. Database records and license plate logs remain 100% intact.
            </p>

            {storageStats && (
              <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-sm)', padding: '0.75rem', marginBottom: '0.85rem', fontSize: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Stored Snapshots:</span>
                  <strong style={{ color: '#FFFFFF' }}>{storageStats.total_files} files ({storageStats.total_size_mb} MB)</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Older than 48 Hours:</span>
                  <span style={{ color: storageStats.old_files > 0 ? 'var(--warning)' : 'var(--success)', fontWeight: 700 }}>
                    {storageStats.old_files} files ({storageStats.old_size_mb} MB)
                  </span>
                </div>
              </div>
            )}

            {cleanMsg && (
              <div style={{ background: 'rgba(16, 185, 129, 0.15)', border: '1px solid var(--success)', borderRadius: 'var(--radius-sm)', padding: '0.5rem 0.75rem', marginBottom: '0.85rem', fontSize: '0.75rem', color: '#FFFFFF', display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <CheckCircle size={14} style={{ color: 'var(--success)', flexShrink: 0 }} />
                <span>{cleanMsg}</span>
              </div>
            )}

            <button 
              className="btn btn-outline" 
              style={{ width: '100%', justifyContent: 'center', fontSize: '0.8rem', padding: '0.55rem' }}
              onClick={handleManualClean}
              disabled={isCleaning}
              id="cleanup-images-btn"
            >
              {isCleaning ? <RefreshCw size={14} className="spin" /> : <Trash2 size={14} />}
              {isCleaning ? 'Cleaning old files...' : 'Clean Old Images Now'}
            </button>
          </div>
        </aside>

        {/* Right: live viewer */}
        <section className="glass-card cam-viewer-card">
          <div className="cam-status-row">
            <span className="cam-status" style={{ color: statusColor }}>
              {status === 'online' ? <Wifi size={16} /> : <WifiOff size={16} />}
              {status === 'online' ? 'Live' : status === 'offline' ? 'Unreachable' : 'Connecting…'}
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              {streamUrl}{frameSize && ` · ${frameSize}`}
            </span>
            <a className="btn btn-outline" href={`${baseUrl}/snapshot`} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Snapshot
            </a>
          </div>

          <div className="cam-viewer">
            <img
              key={`${selected.id}-${streamKey}`}
              src={streamUrl}
              alt={`${selected.name} live stream`}
              onLoad={e => {
                const img = e.currentTarget;
                setStatus('online');
                if (img.naturalWidth) setFrameSize(`${img.naturalWidth}×${img.naturalHeight}`);
              }}
              onError={() => setStatus('offline')}
            />

            {status === 'offline' && (
              <div className="cam-offline">
                <WifiOff size={36} />
                <p>Can't reach the camera at <strong>{selected.host}:{selected.port}</strong></p>
                <small>Make sure edge_tracker.py (or camera_preview.py) is running on the Pi and both devices share a network.</small>
                <button className="btn btn-primary" onClick={reconnect}><RefreshCw size={14} /> Retry</button>
              </div>
            )}

            {showThirds && (
              <div className="cam-overlay cam-thirds">
                <i style={{ left: '33.333%', top: 0, bottom: 0, width: 1 }} />
                <i style={{ left: '66.666%', top: 0, bottom: 0, width: 1 }} />
                <i style={{ top: '33.333%', left: 0, right: 0, height: 1 }} />
                <i style={{ top: '66.666%', left: 0, right: 0, height: 1 }} />
              </div>
            )}
            {showCrosshair && (
              <div className="cam-overlay cam-crosshair">
                <i style={{ left: '50%', top: 0, bottom: 0, width: 1 }} />
                <i style={{ top: '50%', left: 0, right: 0, height: 1 }} />
                <b />
              </div>
            )}
            {showLevel && (
              <div className="cam-overlay cam-level">
                <i style={{ top: '50%', left: '10%', right: '10%', height: 2 }} />
              </div>
            )}
          </div>

          <div className="cam-toggles">
            <label><input type="checkbox" checked={showCrosshair} onChange={e => setShowCrosshair(e.target.checked)} /> Center crosshair</label>
            <label><input type="checkbox" checked={showThirds} onChange={e => setShowThirds(e.target.checked)} /> Rule of thirds</label>
            <label><input type="checkbox" checked={showLevel} onChange={e => setShowLevel(e.target.checked)} /> Level guide</label>
          </div>

          <div className="cam-tips">
            <strong>Mounting checklist</strong>
            <ul>
              <li>The red/green tripwire lines (drawn by the Pi) should sit across the lane where cars pass.</li>
              <li>Keep the horizon level using the level guide, and avoid tilting the camera.</li>
              <li>Vehicle plates should land in the lower third at the closest tripwire.</li>
              <li>Avoid direct headlights or sun glare in the lens; re-check at night.</li>
              <li>Keep the indoor floor (grey masked area) out of the detection corridor.</li>
            </ul>
          </div>
        </section>
      </div>
    </div>
  );
}
