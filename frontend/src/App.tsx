import React, { useState, useEffect, useRef } from 'react';
import { 
  Car, Shield, LogIn, LogOut, Info, Plus, 
  MapPin, Clock, CheckCircle, Search, User, Phone, Edit, Settings, AlertTriangle
} from 'lucide-react';
import CameraSettings from './CameraSettings';

// Dynamic API Configuration (Automatically adapts to localhost, LAN IP 192.168.x.x for phones/tablets, or domain)
const BACKEND_HOST = typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1';
const API_BASE = `http://${BACKEND_HOST}:8000/api`;
const WS_URL = `ws://${BACKEND_HOST}:8000/ws`;
const STATIC_BASE = `http://${BACKEND_HOST}:8000`;

interface Visit {
  id: number;
  plate_number: string;
  color: string;
  brand: string;
  owner_name: string | null;
  owner_phone: string | null;
  zone: string;
  entry_timestamp: string;
  exit_timestamp: string | null;
  status: string;
  entry_image_url: string | null;
  exit_image_url: string | null;
  manually_created: boolean;
  manually_edited: boolean;
}

interface Stats {
  inside_total: number;
  entries_today: number;
  exits_today: number;
  zone_a_inside: number;
  zone_b_inside: number;
}

interface UnverifiedExitCandidate {
  visit_id: number;
  plate_number: string;
  zone: string;
  entry_time?: string;
  color: string;
  brand: string;
}

interface UnverifiedExit {
  scan_id: string;
  zone: string;
  direction: string;
  image_url: string;
  detected_color: string;
  detected_brand: string;
  timestamp: string;
  candidates: UnverifiedExitCandidate[];
}

export default function App() {
  // Authentication State
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [view, setView] = useState<'dashboard' | 'settings'>('dashboard');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  
  // Unverified Exits (reverse or obscured exits)
  const [unverifiedExits, setUnverifiedExits] = useState<UnverifiedExit[]>([]);
  
  // Dashboard Metrics & Logs
  const [stats, setStats] = useState<Stats>({
    inside_total: 0,
    entries_today: 0,
    exits_today: 0,
    zone_a_inside: 0,
    zone_b_inside: 0
  });
  const [visits, setVisits] = useState<Visit[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'All' | 'Inside' | 'Zone A' | 'Zone B'>('All');
  
  // Animation highlights for new logs
  const [highlightIds, setHighlightIds] = useState<number[]>([]);
  
  // Modal Overlays
  const [showManualModal, setShowManualModal] = useState(false);
  const [showEditOwnerModal, setShowEditOwnerModal] = useState(false);
  const [showEditVisitModal, setShowEditVisitModal] = useState(false);
  
  // Selected entities for editing
  const [selectedPlate, setSelectedPlate] = useState('');
  const [selectedVisit, setSelectedVisit] = useState<Visit | null>(null);
  
  // Form Bindings
  const [ownerForm, setOwnerForm] = useState({
    owner_name: '',
    owner_phone: '',
    owner_email: '',
    color: '',
    brand: ''
  });
  
  const [manualForm, setManualForm] = useState({
    plate_number: '',
    zone: 'Zone A',
    direction: 'Entry',
    timestamp: new Date().toISOString().slice(0, 16)
  });
  
  const [visitEditForm, setVisitEditForm] = useState({
    plate_number: '',
    brand: '',
    color: '',
    zone: 'Zone A',
    entry_timestamp: '',
    exit_timestamp: '',
    status: 'Inside'
  });
  
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);

  // Alert structure state
  interface SystemAlert {
    id: string;
    type: string;
    title: string;
    message: string;
    timestamp: string;
    plate_number: string;
    zone: string;
    direction: string;
  }

  const [activeTab, setActiveTab] = useState<'dashboard' | 'alerts'>('dashboard');
  const [activeToasts, setActiveToasts] = useState<SystemAlert[]>([]);
  const [alerts, setAlerts] = useState<SystemAlert[]>(() => {
    const saved = localStorage.getItem('system_alerts');
    return saved ? JSON.parse(saved) : [];
  });

  // Sync alerts history with localStorage
  useEffect(() => {
    localStorage.setItem('system_alerts', JSON.stringify(alerts));
  }, [alerts]);

  interface PendingScan {
    scan_id: string;
    zone: string;
    direction: string;
    image_url: string;
    timestamp: string;
  }
  const [pendingScans, setPendingScans] = useState<PendingScan[]>([]);

  // Web Audio Chimes
  const playEntryChime = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      
      // Note 1: D5 (587.33 Hz)
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(587.33, now);
      gain1.gain.setValueAtTime(0.09, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.3);

      // Note 2: A5 (880 Hz) - bell-like upward resolution
      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(880, now + 0.12);
      gain2.gain.setValueAtTime(0.09, now + 0.12);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.5);
    } catch (e) {
      console.log('Audio feedback blocked by browser settings.');
    }
  };

  const playExitChime = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      
      // Note 1: A5 (880 Hz)
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(880, now);
      gain1.gain.setValueAtTime(0.08, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.25);

      // Note 2: D5 (587.33 Hz) - calming downward release
      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(587.33, now + 0.12);
      gain2.gain.setValueAtTime(0.08, now + 0.12);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.45);
    } catch (e) {
      console.log('Audio feedback blocked by browser settings.');
    }
  };

  const playUnreadableAlertSound = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      
      // Short double alert chirp
      [0, 0.15].forEach(delay => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(740, now + delay);
        gain.gain.setValueAtTime(0.12, now + delay);
        gain.gain.exponentialRampToValueAtTime(0.001, now + delay + 0.1);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + delay);
        osc.stop(now + delay + 0.1);
      });
    } catch (e) {
      console.log('Audio feedback blocked by browser settings.');
    }
  };

  const playNotificationSound = playEntryChime;

  // Play a deeper, buzzing alarm sound for invalid activities
  const playAlertSound = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gain = ctx.createGain();
      
      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ctx.destination);
      
      osc1.type = 'sawtooth';
      osc2.type = 'sawtooth';
      
      osc1.frequency.setValueAtTime(180, ctx.currentTime);
      osc2.frequency.setValueAtTime(184, ctx.currentTime);
      
      gain.gain.setValueAtTime(0.0, ctx.currentTime);
      gain.gain.linearRampToValueAtTime(0.12, ctx.currentTime + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.55);
      
      osc1.start();
      osc2.start();
      osc1.stop(ctx.currentTime + 0.55);
      osc2.stop(ctx.currentTime + 0.55);
    } catch (e) {
      console.log('Audio feedback blocked by browser settings.');
    }
  };


  const triggerAlert = (alert: SystemAlert) => {
    playAlertSound();
    
    // Add to persistent audit log
    setAlerts(prev => [alert, ...prev]);
    
    // Add to floating screen toasts
    setActiveToasts(prev => [alert, ...prev]);
    
    // Dismiss toast warning after 7 seconds
    setTimeout(() => {
      setActiveToasts(prev => prev.filter(t => t.id !== alert.id));
    }, 7000);
  };


  // --- API DATA FETCHERS ---
  
  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/dashboard/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch (e) {
      console.error("Failed to load statistics:", e);
    }
  };

  const fetchHistory = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/visits/history?limit=50`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setVisits(data);
      } else if (res.status === 401) {
        handleLogout();
      }
    } catch (e) {
      console.error("Failed to load visits history:", e);
    }
  };

  // Trigger loading when token changes
  useEffect(() => {
    fetchStats();
    if (token) {
      fetchHistory();
      
      // Establish WebSocket connection
      connectWebSocket();
    }
    
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [token]);

  // --- WEBSOCKET EVENT HANDLER ---
  const connectWebSocket = () => {
    if (wsRef.current) wsRef.current.close();
    
    console.log("[WS] Connecting to server...");
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.event_type === "SCAN_START") {
        console.log("[WS] Scanning started:", msg.scan_id);
        playNotificationSound();
        setPendingScans(prev => [
          {
            scan_id: msg.scan_id,
            zone: msg.zone,
            direction: msg.direction,
            image_url: msg.image_url,
            timestamp: msg.timestamp
          },
          ...prev
        ]);
      } else if (msg.event_type === "VISIT_UPDATE") {
        console.log("[WS] New scan event received:", msg.visit);
        if (msg.visit.plate_number && (msg.visit.plate_number.startsWith('UNREADABLE-') || msg.visit.plate_number.startsWith('CAR-'))) {
          playUnreadableAlertSound();
        } else if (msg.visit.status === 'Completed') {
          playExitChime();
        } else {
          playEntryChime();
        }
        
        // Remove from pending scans
        if (msg.scan_id) {
          setPendingScans(prev => prev.filter(s => s.scan_id !== msg.scan_id));
        }
        
        // Refresh statistics
        fetchStats();
        
        // Prepend or update visits list
        setVisits(prevVisits => {
          const index = prevVisits.findIndex(v => v.id === msg.visit.id);
          if (index !== -1) {
            const updated = [...prevVisits];
            updated[index] = msg.visit;
            return updated;
          } else {
            return [msg.visit, ...prevVisits];
          }
        });
        
        // Trigger highlight pulse
        setHighlightIds(prev => [...prev, msg.visit.id]);
        setTimeout(() => {
          setHighlightIds(prev => prev.filter(id => id !== msg.visit.id));
        }, 5000);
      } else if (msg.event_type === "SYSTEM_ALERT") {
        console.log("[WS] System warning received:", msg.alert);
        triggerAlert(msg.alert);
        if (msg.scan_id) {
          setPendingScans(prev => prev.filter(s => s.scan_id !== msg.scan_id));
        }
      } else if (msg.event_type === "UNVERIFIED_EXIT") {
        console.log("[WS] Unverified exit received:", msg);
        playNotificationSound();
        setUnverifiedExits(prev => [
          {
            scan_id: msg.scan_id,
            zone: msg.zone,
            direction: msg.direction,
            image_url: msg.image_url,
            detected_color: msg.detected_color || "Unknown",
            detected_brand: msg.detected_brand || "Unknown",
            timestamp: msg.timestamp,
            candidates: msg.candidates || []
          },
          ...prev.filter(u => u.scan_id !== msg.scan_id)
        ]);
        if (msg.scan_id) {
          setPendingScans(prev => prev.filter(s => s.scan_id !== msg.scan_id));
        }
      } else if (msg.event_type === "SCAN_FAIL") {
        console.log("[WS] Scanning failed:", msg.scan_id, msg.detail);
        if (msg.scan_id) {
          setPendingScans(prev => prev.filter(s => s.scan_id !== msg.scan_id));
        }
      }
    };
    
    ws.onclose = () => {
      console.log("[WS] Connection lost. Reconnecting in 5 seconds...");
      setTimeout(() => {
        if (token) connectWebSocket();
      }, 5000);
    };
  };

  // --- EVENT HANDLERS ---

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData
      });
      
      if (res.ok) {
        const data = await res.json();
        localStorage.setItem('token', data.access_token);
        setToken(data.access_token);
        setUsername('');
        setPassword('');
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || 'Login failed.');
      }
    } catch (e) {
      setErrorMsg('Cannot reach authentication server.');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setVisits([]);
    if (wsRef.current) wsRef.current.close();
  };

  // Create Manual Visit Entry
  const handleCreateManualVisit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    
    const bodyForm = new FormData();
    bodyForm.append('plate_number', manualForm.plate_number);
    bodyForm.append('zone', manualForm.zone);
    bodyForm.append('direction', manualForm.direction);
    bodyForm.append('timestamp', new Date(manualForm.timestamp).toISOString());

    try {
      const res = await fetch(`${API_BASE}/visits/manual`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: bodyForm
      });

      if (res.ok) {
        setSuccessMsg("Manual visit log registered successfully.");
        setShowManualModal(false);
        fetchStats();
        fetchHistory();
        setManualForm({
          plate_number: '',
          zone: 'Zone A',
          direction: 'Entry',
          timestamp: new Date().toISOString().slice(0, 16)
        });
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || "Failed to create visit log.");
      }
    } catch (e) {
      setErrorMsg("Connection failure.");
    }
  };

  // Open Edit Owner Modal
  const openEditOwner = (visit: Visit) => {
    setSelectedPlate(visit.plate_number);
    setOwnerForm({
      owner_name: visit.owner_name || '',
      owner_phone: visit.owner_phone || '',
      owner_email: '', // Not sent in feed, will be editable
      color: visit.color || '',
      brand: visit.brand || ''
    });
    
    // Fetch detailed vehicle data first to pre-fill email
    fetch(`${API_BASE}/vehicles/${visit.plate_number}`)
      .then(res => res.json())
      .then(data => {
        setOwnerForm({
          owner_name: data.owner_name || '',
          owner_phone: data.owner_phone || '',
          owner_email: data.owner_email || '',
          color: data.color || '',
          brand: data.brand || ''
        });
      }).catch(() => {});
      
    setShowEditOwnerModal(true);
  };

  // Save Owner Modifications
  const handleSaveOwner = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    
    const bodyForm = new FormData();
    bodyForm.append('owner_name', ownerForm.owner_name);
    bodyForm.append('owner_phone', ownerForm.owner_phone);
    bodyForm.append('owner_email', ownerForm.owner_email);
    bodyForm.append('color', ownerForm.color);
    bodyForm.append('brand', ownerForm.brand);

    try {
      const res = await fetch(`${API_BASE}/vehicles/${selectedPlate}`, {
        method: 'PUT',
        headers: { 'Authorization': `Bearer ${token}` },
        body: bodyForm
      });
      
      if (res.ok) {
        setSuccessMsg("Vehicle owner details updated successfully.");
        setShowEditOwnerModal(false);
        fetchHistory();
      } else {
        setErrorMsg("Failed to update owner profile.");
      }
    } catch (e) {
      setErrorMsg("Connection error.");
    }
  };

  // Open Edit Visit Log Modal
  const openEditVisit = (visit: Visit) => {
    setSelectedVisit(visit);
    setVisitEditForm({
      plate_number: visit.plate_number,
      brand: visit.brand || '',
      color: visit.color || '',
      zone: visit.zone,
      entry_timestamp: new Date(visit.entry_timestamp).toISOString().slice(0, 16),
      exit_timestamp: visit.exit_timestamp ? new Date(visit.exit_timestamp).toISOString().slice(0, 16) : '',
      status: visit.status
    });
    setShowEditVisitModal(true);
  };

  // Save Visit Log Modifications
  const handleSaveVisitEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedVisit) return;
    setErrorMsg(null);
    setSuccessMsg(null);

    const bodyForm = new FormData();
    bodyForm.append('plate_number', visitEditForm.plate_number);
    bodyForm.append('brand', visitEditForm.brand);
    bodyForm.append('color', visitEditForm.color);
    bodyForm.append('zone', visitEditForm.zone);
    bodyForm.append('entry_timestamp', new Date(visitEditForm.entry_timestamp).toISOString());
    bodyForm.append('status', visitEditForm.status);
    
    if (visitEditForm.status === 'Completed' && visitEditForm.exit_timestamp) {
      bodyForm.append('exit_timestamp', new Date(visitEditForm.exit_timestamp).toISOString());
    } else if (visitEditForm.status === 'Inside') {
      bodyForm.append('exit_timestamp', ''); // Clears out timestamp
    }

    try {
      const res = await fetch(`${API_BASE}/visits/${selectedVisit.id}`, {
        method: 'PUT',
        headers: { 'Authorization': `Bearer ${token}` },
        body: bodyForm
      });

      if (res.ok) {
        setSuccessMsg("Visit log updated successfully.");
        setShowEditVisitModal(false);
        fetchStats();
        fetchHistory();
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || "Failed to update visit record.");
      }
    } catch (e) {
      setErrorMsg("Connection error.");
    }
  };

  const handleConfirmExit = async (visitId: number, imageUrl: string, scanId: string) => {
    try {
      const res = await fetch(`${API_BASE}/visits/confirm-unverified-exit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ visit_id: visitId, exit_image_url: imageUrl })
      });
      if (res.ok) {
        setUnverifiedExits(prev => prev.filter(u => u.scan_id !== scanId));
        setSuccessMsg("Vehicle exit confirmed successfully!");
        fetchStats();
        fetchHistory();
      } else {
        const err = await res.json();
        setErrorMsg(err.detail || "Failed to confirm exit.");
      }
    } catch (e) {
      setErrorMsg("Connection error confirming exit.");
    }
  };

  // Format Helper for timestamps
  const formatTime = (isoString: string) => {
    const dateObj = new Date(isoString);
    return dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + 
           ' (' + dateObj.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ')';
  };

  // Filter history based on search query and category filters
  const filteredVisits = visits.filter(v => {
    const query = searchQuery.toLowerCase();
    const matchesSearch = query === '' || 
      v.plate_number.toLowerCase().includes(query) || 
      v.brand.toLowerCase().includes(query) || 
      (v.owner_name && v.owner_name.toLowerCase().includes(query));

    let matchesCategory = true;
    if (statusFilter === 'Inside') {
      matchesCategory = v.status === 'Inside';
    } else if (statusFilter === 'Zone A') {
      matchesCategory = v.zone === 'Zone A';
    } else if (statusFilter === 'Zone B') {
      matchesCategory = v.zone === 'Zone B';
    }

    return matchesSearch && matchesCategory;
  });

  const filteredPendingScans = pendingScans.filter(scan => {
    let matchesCategory = true;
    if (statusFilter === 'Zone A') {
      matchesCategory = scan.zone === 'Zone A';
    } else if (statusFilter === 'Zone B') {
      matchesCategory = scan.zone === 'Zone B';
    }
    return matchesCategory;
  });


  // --- RENDER LOGIN VIEW ---
  
  if (!token) {
    return (
      <div className="login-container">
        <div className="login-card glass-card">
          <div className="login-header">
            <div className="brand-icon">
              <Shield size={24} color="#FFFFFF" />
            </div>
            <h1 className="brand-title" style={{ WebkitTextFillColor: 'unset', color: '#FFFFFF' }}>Workshop Portal</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Login to manage workshop feeds</p>
          </div>
          
          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input 
                type="text" 
                className="form-input" 
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="admin" 
                required 
              />
            </div>
            
            <div className="form-group">
              <label className="form-label">Password</label>
              <input 
                type="password" 
                className="form-input" 
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="adminpassword123" 
                required 
              />
            </div>
            
            {errorMsg && (
              <p style={{ color: 'var(--danger)', fontSize: '0.85rem', fontWeight: 600, textAlign: 'center' }}>
                {errorMsg}
              </p>
            )}
            
            <button type="submit" className="btn btn-primary" style={{ justifyContent: 'center', marginTop: '0.5rem' }}>
              <LogIn size={18} /> Sign In
            </button>
          </form>
        </div>
      </div>
    );
  }

  // --- RENDER SETTINGS VIEW ---
  if (view === 'settings') {
    return <CameraSettings onBack={() => setView('dashboard')} />;
  }

  // --- RENDER DASHBOARD VIEW ---

  return (
    <div className="app-container">
      {/* Floating System Alerts (Toast List) */}
      <div style={{ position: 'fixed', top: '1.5rem', right: '1.5rem', zIndex: 9999, display: 'flex', flexDirection: 'column', gap: '0.75rem', maxWidth: '380px', width: '100%' }}>
        {activeToasts.map(alert => (
          <div 
            key={alert.id} 
            className="glass-card animate-slide-in" 
            style={{ 
              padding: '1.1rem 1.4rem', 
              borderLeft: `4px solid ${alert.type === 'Danger' ? 'var(--danger)' : 'var(--warning)'}`,
              background: 'rgba(15, 23, 42, 0.93)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.3rem',
              boxShadow: '0 12px 30px -5px rgba(0, 0, 0, 0.75)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ color: '#FFFFFF', fontSize: '0.95rem', fontWeight: 800 }}>{alert.title}</strong>
              <button 
                onClick={() => setActiveToasts(prev => prev.filter(t => t.id !== alert.id))}
                style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '1.2rem', padding: '0 0.2rem', lineHeight: 1 }}
              >
                &times;
              </button>
            </div>
            <span style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', lineHeight: 1.3 }}>{alert.message}</span>
            <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.725rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              <span>Plate: <strong>{alert.plate_number}</strong></span>
              <span>&bull;</span>
              <span>{alert.zone}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Top Banner Alert System */}
      {successMsg && (
        <div style={{ background: 'var(--success-glow)', border: '1px solid var(--success)', borderRadius: 'var(--radius-sm)', padding: '0.85rem 1.25rem', display: 'flex', justifyContent: 'space-between', color: '#FFFFFF' }}>
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} style={{ background: 'none', border: 'none', color: '#FFFFFF', cursor: 'pointer', fontWeight: 'bold' }}>x</button>
        </div>
      )}
      {errorMsg && (
        <div style={{ background: 'var(--danger-glow)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-sm)', padding: '0.85rem 1.25rem', display: 'flex', justifyContent: 'space-between', color: '#FFFFFF' }}>
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', color: '#FFFFFF', cursor: 'pointer', fontWeight: 'bold' }}>x</button>
        </div>
      )}

      {/* Header */}
      <header className="app-header glass-card">
        <div className="brand-section">
          <div className="brand-icon">
            <Car size={24} color="#FFFFFF" />
          </div>
          <div>
            <h1 className="brand-title">CallMyCar</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Workshop Visits Tracker</p>
          </div>
        </div>
        
        <div className="header-actions">
          <span className="user-tag">Admin Mode</span>
          <button className="btn btn-outline" onClick={() => setView('settings')} id="open-settings-btn">
            <Settings size={16} /> Settings
          </button>
          <button className="btn btn-outline" onClick={handleLogout}>
            <LogOut size={16} /> Sign Out
          </button>
        </div>
      </header>

      {/* Unverified Exit Cards (Interactive resolution for reverse/obscured exits) */}
      {unverifiedExits.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.25rem' }}>
          {unverifiedExits.map((item) => (
            <div 
              key={item.scan_id}
              className="glass-card animate-slide-in"
              style={{
                borderLeft: '4px solid var(--warning)',
                background: 'rgba(30, 41, 59, 0.96)',
                padding: '1rem 1.25rem',
                display: 'flex',
                flexWrap: 'wrap',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '1rem',
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <img 
                  src={`${API_BASE}${item.image_url}`} 
                  alt="Exit snapshot" 
                  style={{ width: '85px', height: '58px', objectFit: 'cover', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.2)' }}
                />
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ background: 'rgba(234, 179, 8, 0.25)', color: '#facc15', fontSize: '0.75rem', fontWeight: 700, padding: '0.2rem 0.6rem', borderRadius: '4px', border: '1px solid rgba(234, 179, 8, 0.4)' }}>
                      Vehicle Exited (Plate Obscured / Reverse)
                    </span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{item.zone}</span>
                  </div>
                  <p style={{ margin: '0.35rem 0 0 0', fontSize: '0.875rem', color: '#f1f5f9' }}>
                    Departure motion recorded. Detected color: <strong>{item.detected_color}</strong>
                  </p>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Confirm which car exited:</span>
                {item.candidates.length > 0 ? (
                  item.candidates.map((cand) => (
                    <button
                      key={cand.visit_id}
                      onClick={() => handleConfirmExit(cand.visit_id, item.image_url, item.scan_id)}
                      className="btn btn-primary"
                      style={{ padding: '0.45rem 0.9rem', fontSize: '0.825rem', background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', border: 'none', cursor: 'pointer' }}
                    >
                      ✓ <strong>{cand.plate_number}</strong> ({cand.color} {cand.brand})
                    </button>
                  ))
                ) : (
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>No cars logged inside</span>
                )}
                <button
                  onClick={() => setUnverifiedExits(prev => prev.filter(u => u.scan_id !== item.scan_id))}
                  className="btn btn-outline"
                  style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem', cursor: 'pointer' }}
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Navigation Tabs */}
      <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-light)', paddingBottom: '1rem', marginBottom: '0.5rem' }}>
        <button 
          className={`btn ${activeTab === 'dashboard' ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => setActiveTab('dashboard')}
          style={{ padding: '0.5rem 1.25rem' }}
        >
          <Car size={16} /> Activity Dashboard
        </button>
        <button 
          className={`btn ${activeTab === 'alerts' ? 'btn-primary' : 'btn-outline'}`}
          onClick={() => setActiveTab('alerts')}
          style={{ padding: '0.5rem 1.25rem', position: 'relative' }}
        >
          <Shield size={16} /> System Alerts Audit
          {alerts.length > 0 && (
            <span style={{ position: 'absolute', top: '-6px', right: '-6px', background: 'var(--danger)', color: '#FFFFFF', fontSize: '0.65rem', fontWeight: 800, padding: '0.15rem 0.4rem', borderRadius: '10px', boxShadow: '0 2px 4px rgba(0,0,0,0.5)' }}>
              {alerts.length}
            </span>
          )}
        </button>
      </div>

      {/* --- TAB VIEW A: ACTIVITY DASHBOARD --- */}
      {activeTab === 'dashboard' && (
        <>
          {/* Statistics Display */}
          <div className="stats-grid">
            <div className="stat-card glass-card">
              <div className="stat-info">
                <span className="stat-label">Currently Inside</span>
                <span className="stat-val">{stats.inside_total}</span>
              </div>
              <div className="stat-icon primary">
                <Car size={28} />
              </div>
            </div>

            <div className="stat-card glass-card">
              <div className="stat-info">
                <span className="stat-label">Entries Today</span>
                <span className="stat-val">{stats.entries_today}</span>
              </div>
              <div className="stat-icon success">
                <LogIn size={28} />
              </div>
            </div>

            <div className="stat-card glass-card">
              <div className="stat-info">
                <span className="stat-label">Exits Today</span>
                <span className="stat-val">{stats.exits_today}</span>
              </div>
              <div className="stat-icon danger">
                <LogOut size={28} />
              </div>
            </div>

            <div className="stat-card glass-card">
              <div className="stat-info">
                <span className="stat-label">Zone Breakdown</span>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                  Zone A (Ground): <strong>{stats.zone_a_inside}</strong> <br />
                  Zone B (Basement): <strong>{stats.zone_b_inside}</strong>
                </span>
              </div>
              <div className="stat-icon primary" style={{ color: 'var(--warning)', background: 'rgba(245, 158, 11, 0.08)', borderColor: 'rgba(245, 158, 11, 0.2)' }}>
                <MapPin size={28} />
              </div>
            </div>
          </div>

          {/* Primary Dashboard Sections */}
          <div className="dashboard-content">
            
            {/* Real-time event log */}
            <div className="feed-panel glass-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                <h2 className="section-title" style={{ marginBottom: 0 }}>
                  <Clock size={20} /> Real-time Activity Feed
                </h2>
                <button className="btn btn-primary" onClick={() => setShowManualModal(true)}>
                  <Plus size={16} /> Log Manual Visit
                </button>
              </div>
              
              <div className="event-list">
                {filteredVisits.length === 0 && filteredPendingScans.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Info size={36} style={{ marginBottom: '1rem', color: 'var(--primary)' }} />
                    <p>No activity logs found matching the filters.</p>
                  </div>
                ) : (
                  <>
                    {/* Render Pending Scans (Instant Skeleton Loader Cards) */}
                    {filteredPendingScans.map(scan => (
                      <div 
                        key={scan.scan_id} 
                        className="event-card" 
                        style={{ 
                          border: '1px dashed var(--primary)', 
                          background: 'rgba(99, 102, 241, 0.04)',
                          position: 'relative',
                          overflow: 'hidden'
                        }}
                      >
                        {/* Shimmer overlay */}
                        <div 
                          style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            right: 0,
                            bottom: 0,
                            background: 'linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.08), transparent)',
                            animation: 'shimmer 1.8s infinite',
                            width: '200%',
                            pointerEvents: 'none'
                          }}
                        />

                        {/* Snapshot thumbnail */}
                        <img 
                          src={`${STATIC_BASE}${scan.image_url}`} 
                          alt="Incoming snapshot" 
                          className="event-thumbnail"
                          style={{ filter: 'blur(3px) grayscale(50%)', opacity: 0.6 }}
                        />

                        <div className="event-details" style={{ flex: 1 }}>
                          <div className="event-header">
                            <span className="plate-badge" style={{ color: 'var(--text-muted)', borderStyle: 'dashed' }}>
                              SCANNING...
                            </span>
                            <span className={`badge ${scan.direction === 'Exit' ? 'badge-exit' : 'badge-entry'}`} style={{ opacity: 0.85 }}>
                              {scan.direction === 'Exit' ? 'Exiting' : 'Entering'}
                            </span>
                            <span className="badge badge-zone">{scan.zone}</span>
                          </div>
                          
                          <div style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.2rem' }}>
                            <span style={{
                              width: '12px',
                              height: '12px',
                              border: '2px solid var(--border-light)',
                              borderTop: '2px solid var(--primary)',
                              borderRadius: '50%',
                              animation: 'spin 0.8s linear infinite',
                              display: 'inline-block'
                            }} />
                            <span style={{ fontWeight: 500, color: '#FFFFFF' }}>AI Engine analyzing plate...</span>
                          </div>
                        </div>
                      </div>
                    ))}

                    {/* Render Realized Visits */}
                    {filteredVisits.map(visit => {
                      const isNew = highlightIds.includes(visit.id);
                      const isExit = visit.status === 'Completed';
                      const latestImage = isExit ? visit.exit_image_url : visit.entry_image_url;
                      
                      return (
                        <div key={visit.id} className={`event-card ${isNew ? 'new-item' : ''}`}>
                          {/* Event image */}
                          {latestImage ? (
                            <img 
                              src={`${STATIC_BASE}${latestImage}`} 
                              alt="Vehicle crop" 
                              className="event-thumbnail"
                              onError={(e) => {
                                (e.target as HTMLImageElement).src = 'https://images.unsplash.com/photo-1549399542-7e3f8b79c341?q=80&w=200&auto=format&fit=crop';
                              }}
                            />
                          ) : (
                            <div className="event-thumbnail" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                              <Car size={24} />
                            </div>
                          )}
                          
                          {/* Event meta and AI specs */}
                          <div className="event-details">
                            <div className="event-header">
                              {visit.plate_number.startsWith('UNREADABLE-') || visit.plate_number.startsWith('CAR-') ? (
                                <span className="plate-badge" style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#EF4444', borderColor: '#EF4444', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                                  <AlertTriangle size={14} /> {visit.plate_number}
                                </span>
                              ) : (
                                <span className="plate-badge">{visit.plate_number}</span>
                              )}
                              <span className={`badge ${isExit ? 'badge-exit' : 'badge-entry'}`}>
                                {isExit ? 'Exited' : 'Entered'}
                              </span>
                              <span className="badge badge-zone">{visit.zone}</span>
                              {visit.manually_created && <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.1)', color: 'var(--warning)', border: '1px solid rgba(245, 158, 11, 0.2)' }}>Manual API</span>}
                              {visit.manually_edited && <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.1)', color: 'var(--primary)', border: '1px solid rgba(99, 102, 241, 0.2)' }}>Edited</span>}
                              {(visit.plate_number.startsWith('UNREADABLE-') || visit.plate_number.startsWith('CAR-')) && (
                                <button 
                                  className="btn btn-outline" 
                                  style={{ padding: '0.2rem 0.6rem', fontSize: '0.75rem', borderColor: '#EF4444', color: '#EF4444', fontWeight: 600 }}
                                  onClick={() => openEditVisit(visit)}
                                >
                                  Identify Plate
                                </button>
                              )}
                            </div>
                            
                            <div className="event-meta">
                              <span className="meta-item">
                                <strong>Color:</strong> {visit.color}
                              </span>
                              <span className="meta-item">
                                <strong>Brand:</strong> {visit.brand}
                              </span>
                              <span className="meta-item">
                                <strong>Time:</strong> {formatTime(isExit && visit.exit_timestamp ? visit.exit_timestamp : visit.entry_timestamp)}
                              </span>
                            </div>
                            
                            {/* Owner Quick Readout */}
                            {visit.owner_name ? (
                              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', gap: '0.75rem', marginTop: '0.15rem' }}>
                                <span style={{ display: 'flex', alignItems: 'center', gap: '0.15rem' }}>
                                  <User size={12} /> {visit.owner_name}
                                </span>
                                <span style={{ display: 'flex', alignItems: 'center', gap: '0.15rem' }}>
                                  <Phone size={12} /> {visit.owner_phone}
                                </span>
                              </div>
                            ) : (
                              <button 
                                onClick={() => openEditOwner(visit)}
                                style={{ alignSelf: 'flex-start', background: 'none', border: 'none', color: 'var(--primary)', fontSize: '0.75rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.15rem', marginTop: '0.15rem', textDecoration: 'underline' }}
                              >
                                + Add Owner Info
                              </button>
                            )}
                          </div>
                          
                          {/* Action buttons */}
                          <div className="event-actions">
                            <button className="btn btn-outline" style={{ padding: '0.4rem 0.6rem' }} title="Edit Owner Information" onClick={() => openEditOwner(visit)}>
                              <User size={14} />
                            </button>
                            <button className="btn btn-outline" style={{ padding: '0.4rem 0.6rem' }} title="Edit Visit log" onClick={() => openEditVisit(visit)}>
                              <Edit size={14} />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </div>

            {/* Side Panel (Search and Vehicles List) */}
            <div className="sidebar-panel glass-card">
              <h2 className="section-title" style={{ marginBottom: '0.25rem' }}>
                <Search size={20} /> Search Database
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
                Filter events by plate or customer name
              </p>
              
              <input 
                type="text" 
                className="search-bar" 
                placeholder="Search license plate, brand, owner..." 
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
              
              <div style={{ borderTop: '1px solid var(--border-light)', margin: '1rem 0' }}></div>
              
              <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#FFFFFF', marginBottom: '0.75rem' }}>
                Quick Filter Shortcuts
              </h3>
              
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                <button 
                  className={`btn ${statusFilter === 'All' ? 'btn-primary' : 'btn-outline'}`} 
                  style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }} 
                  onClick={() => setStatusFilter('All')}
                >
                  All
                </button>
                <button 
                  className={`btn ${statusFilter === 'Inside' ? 'btn-primary' : 'btn-outline'}`} 
                  style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }} 
                  onClick={() => setStatusFilter('Inside')}
                >
                  Inside Now
                </button>
                <button 
                  className={`btn ${statusFilter === 'Zone A' ? 'btn-primary' : 'btn-outline'}`} 
                  style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }} 
                  onClick={() => setStatusFilter('Zone A')}
                >
                  Zone A
                </button>
                <button 
                  className={`btn ${statusFilter === 'Zone B' ? 'btn-primary' : 'btn-outline'}`} 
                  style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }} 
                  onClick={() => setStatusFilter('Zone B')}
                >
                  Zone B
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* --- TAB VIEW B: SYSTEM ALERTS AUDIT --- */}
      {activeTab === 'alerts' && (
        <div className="glass-card" style={{ padding: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <h2 className="section-title" style={{ marginBottom: '0.25rem' }}>
                <Shield size={22} style={{ color: 'var(--danger)' }} /> System Warnings & Alerts Audit
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                Historical log of invalid entries, exits, and duplicate system conflicts
              </p>
            </div>
            {alerts.length > 0 && (
              <button 
                className="btn btn-danger" 
                onClick={() => {
                  if (window.confirm("Are you sure you want to clear the entire alerts history?")) {
                    setAlerts([]);
                  }
                }}
              >
                Clear Alerts History
              </button>
            )}
          </div>

          {alerts.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-secondary)' }}>
              <CheckCircle size={48} style={{ marginBottom: '1rem', color: 'var(--success)' }} />
              <h3 style={{ color: '#FFFFFF', marginBottom: '0.5rem' }}>No System Alerts</h3>
              <p>Everything is running smoothly. Blocked/invalid activities will show up here.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {alerts.map(alert => (
                <div 
                  key={alert.id} 
                  className="glass-card" 
                  style={{ 
                    padding: '1.25rem', 
                    borderLeft: `4px solid ${alert.type === 'Danger' ? 'var(--danger)' : 'var(--warning)'}`,
                    background: 'rgba(255, 255, 255, 0.01)',
                    display: 'grid',
                    gridTemplateColumns: '1fr auto',
                    alignItems: 'center',
                    gap: '1rem'
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                      <span style={{ 
                        fontSize: '0.7rem', 
                        fontWeight: 'bold', 
                        textTransform: 'uppercase',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '4px',
                        background: alert.type === 'Danger' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                        color: alert.type === 'Danger' ? 'var(--danger)' : 'var(--warning)',
                        border: `1px solid ${alert.type === 'Danger' ? 'var(--danger-glow)' : 'rgba(245, 158, 11, 0.2)'}`
                      }}>
                        {alert.type}
                      </span>
                      <strong style={{ color: '#FFFFFF', fontSize: '1rem' }}>{alert.title}</strong>
                      <span className="badge badge-zone" style={{ fontSize: '0.7rem' }}>{alert.zone}</span>
                      <span className="plate-badge" style={{ fontSize: '0.8rem', padding: '0.1rem 0.35rem' }}>{alert.plate_number}</span>
                    </div>
                    <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{alert.message}</span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      <strong>Occurred:</strong> {formatTime(alert.timestamp)}
                    </span>
                  </div>
                  <button 
                    className="btn btn-outline" 
                    style={{ padding: '0.4rem 0.6rem', color: 'var(--danger)', borderColor: 'rgba(239, 68, 68, 0.2)' }}
                    onClick={() => setAlerts(prev => prev.filter(a => a.id !== alert.id))}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}


      {/* --- MODAL: CREATE MANUAL VISIT --- */}
      {showManualModal && (
        <div className="modal-overlay">
          <div className="modal-content glass-card">
            <div className="modal-header">
              <h3 style={{ color: '#FFFFFF', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Plus size={20} color="var(--primary)" /> Log Manual Visit
              </h3>
              <button className="modal-close" onClick={() => setShowManualModal(false)}>x</button>
            </div>
            
            <form onSubmit={handleCreateManualVisit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Plate Number</label>
                <input 
                  type="text" 
                  className="form-input" 
                  style={{ textTransform: 'uppercase' }}
                  value={manualForm.plate_number}
                  onChange={e => setManualForm({...manualForm, plate_number: e.target.value})}
                  placeholder="e.g. DXB1234"
                  required 
                />
              </div>
              
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Zone</label>
                  <select 
                    className="form-select"
                    value={manualForm.zone}
                    onChange={e => setManualForm({...manualForm, zone: e.target.value})}
                  >
                    <option value="Zone A">Zone A (Ground)</option>
                    <option value="Zone B">Zone B (Basement)</option>
                  </select>
                </div>
                
                <div className="form-group">
                  <label className="form-label">Direction</label>
                  <select 
                    className="form-select"
                    value={manualForm.direction}
                    onChange={e => setManualForm({...manualForm, direction: e.target.value})}
                  >
                    <option value="Entry">Entry</option>
                    <option value="Exit">Exit</option>
                  </select>
                </div>
              </div>
              
              <div className="form-group">
                <label className="form-label">Timestamp</label>
                <input 
                  type="datetime-local" 
                  className="form-input" 
                  value={manualForm.timestamp}
                  onChange={e => setManualForm({...manualForm, timestamp: e.target.value})}
                  required 
                />
              </div>
              
              <div className="modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => setShowManualModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Confirm log
                </button>
              </div>
            </form>
          </div>
        </div>
      )}


      {/* --- MODAL: EDIT OWNER INFO --- */}
      {showEditOwnerModal && (
        <div className="modal-overlay">
          <div className="modal-content glass-card">
            <div className="modal-header">
              <h3 style={{ color: '#FFFFFF', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <User size={20} color="var(--primary)" /> Owner & Vehicle Details
              </h3>
              <button className="modal-close" onClick={() => setShowEditOwnerModal(false)}>x</button>
            </div>
            
            <form onSubmit={handleSaveOwner} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div style={{ background: '#111827', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-light)' }}>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Plate Number:</span>
                <div style={{ fontFamily: 'monospace', fontSize: '1.2rem', fontWeight: 'bold', color: '#FFFFFF' }}>{selectedPlate}</div>
              </div>
              
              <div className="form-group">
                <label className="form-label">Owner Name</label>
                <input 
                  type="text" 
                  className="form-input" 
                  value={ownerForm.owner_name}
                  onChange={e => setOwnerForm({...ownerForm, owner_name: e.target.value})}
                  placeholder="e.g. John Doe"
                  required 
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Owner Phone</label>
                  <input 
                    type="tel" 
                    className="form-input" 
                    value={ownerForm.owner_phone}
                    onChange={e => setOwnerForm({...ownerForm, owner_phone: e.target.value})}
                    placeholder="e.g. +971501234567"
                    required 
                  />
                </div>
                
                <div className="form-group">
                  <label className="form-label">Owner Email</label>
                  <input 
                    type="email" 
                    className="form-input" 
                    value={ownerForm.owner_email}
                    onChange={e => setOwnerForm({...ownerForm, owner_email: e.target.value})}
                    placeholder="e.g. name@example.com"
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Vehicle Color</label>
                  <input 
                    type="text" 
                    className="form-input" 
                    value={ownerForm.color}
                    onChange={e => setOwnerForm({...ownerForm, color: e.target.value})}
                    placeholder="e.g. Red"
                  />
                </div>
                
                <div className="form-group">
                  <label className="form-label">Vehicle Brand</label>
                  <input 
                    type="text" 
                    className="form-input" 
                    value={ownerForm.brand}
                    onChange={e => setOwnerForm({...ownerForm, brand: e.target.value})}
                    placeholder="e.g. Nissan"
                  />
                </div>
              </div>
              
              <div className="modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => setShowEditOwnerModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Details
                </button>
              </div>
            </form>
          </div>
        </div>
      )}


      {/* --- MODAL: EDIT VISIT LOG --- */}
      {showEditVisitModal && (
        <div className="modal-overlay">
          <div className="modal-content glass-card">
            <div className="modal-header">
              <h3 style={{ color: '#FFFFFF', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Edit size={20} color="var(--primary)" /> Modify Visit Record
              </h3>
              <button className="modal-close" onClick={() => setShowEditVisitModal(false)}>x</button>
            </div>
            
            {/* Snapshot Preview if available */}
            {selectedVisit && (selectedVisit.entry_image_url || selectedVisit.exit_image_url) && (
              <div style={{ marginBottom: '1rem', borderRadius: '10px', overflow: 'hidden', border: '1px solid var(--border-light)', maxHeight: '200px', display: 'flex', justifyContent: 'center', background: '#000' }}>
                <img 
                  src={`${STATIC_BASE}${selectedVisit.entry_image_url || selectedVisit.exit_image_url}`} 
                  alt="Vehicle Gate Capture" 
                  style={{ maxHeight: '200px', width: 'auto', objectFit: 'contain' }}
                />
              </div>
            )}

            <form onSubmit={handleSaveVisitEdit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="form-group">
                <label className="form-label">Plate Number (Clean uppercase, e.g. M 11770 or 55456)</label>
                <input 
                  type="text" 
                  className="form-input" 
                  style={{ textTransform: 'uppercase', fontWeight: 600, fontSize: '1.1rem' }}
                  value={visitEditForm.plate_number}
                  onChange={e => setVisitEditForm({...visitEditForm, plate_number: e.target.value})}
                  placeholder="e.g. 55456 or M 11770"
                  required 
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Brand / Make</label>
                  <input 
                    type="text" 
                    className="form-input" 
                    value={visitEditForm.brand}
                    onChange={e => setVisitEditForm({...visitEditForm, brand: e.target.value})}
                    placeholder="e.g. Porsche, Toyota, Mercedes"
                  />
                </div>
                
                <div className="form-group">
                  <label className="form-label">Color</label>
                  <select 
                    className="form-select"
                    value={visitEditForm.color}
                    onChange={e => setVisitEditForm({...visitEditForm, color: e.target.value})}
                  >
                    <option value="Unknown">Select Color...</option>
                    <option value="White">White</option>
                    <option value="Black">Black</option>
                    <option value="Silver/Grey">Silver / Grey</option>
                    <option value="Blue">Blue</option>
                    <option value="Red">Red</option>
                    <option value="Brown/Gold">Brown / Gold</option>
                    <option value="Green">Green</option>
                    <option value="Yellow">Yellow</option>
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Zone</label>
                  <select 
                    className="form-select"
                    value={visitEditForm.zone}
                    onChange={e => setVisitEditForm({...visitEditForm, zone: e.target.value})}
                  >
                    <option value="Zone A">Zone A (Ground)</option>
                    <option value="Zone B">Zone B (Basement)</option>
                  </select>
                </div>
                
                <div className="form-group">
                  <label className="form-label">Status</label>
                  <select 
                    className="form-select"
                    value={visitEditForm.status}
                    onChange={e => setVisitEditForm({...visitEditForm, status: e.target.value})}
                  >
                    <option value="Inside">Inside (Active)</option>
                    <option value="Completed">Completed (Exited)</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Entry Timestamp</label>
                <input 
                  type="datetime-local" 
                  className="form-input" 
                  value={visitEditForm.entry_timestamp}
                  onChange={e => setVisitEditForm({...visitEditForm, entry_timestamp: e.target.value})}
                  required 
                />
              </div>

              {visitEditForm.status === 'Completed' && (
                <div className="form-group">
                  <label className="form-label">Exit Timestamp</label>
                  <input 
                    type="datetime-local" 
                    className="form-input" 
                    value={visitEditForm.exit_timestamp}
                    onChange={e => setVisitEditForm({...visitEditForm, exit_timestamp: e.target.value})}
                    required 
                  />
                </div>
              )}
              
              <div className="modal-actions">
                <button type="button" className="btn btn-outline" onClick={() => setShowEditVisitModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
