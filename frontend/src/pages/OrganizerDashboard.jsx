import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Calendar, Image, Users, CheckCircle2, Clock, X, ArrowRight, Loader2, Key } from 'lucide-react';
import api from '../api/client';

export default function OrganizerDashboard() {
  const [events, setEvents]   = useState([]);
  const [sub, setSub]         = useState(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', description: '' });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [evRes] = await Promise.all([api.get('/api/events/')]);
      setEvents(evRes.data);
      // Sub info comes via tenant detail — mock from first event context
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const createEvent = async () => {
    if (!form.name.trim()) return;
    setCreating(true); setCreateError('');
    try {
      await api.post('/api/events/', form);
      setShowCreate(false);
      setForm({ name: '', description: '' });
      loadData();
    } catch (e) { setCreateError(e.response?.data?.detail || 'Failed to create event'); }
    finally { setCreating(false); }
  };

  const totalPhotos   = events.reduce((s, e) => s + (e.photo_count || 0), 0);
  const totalClusters = events.reduce((s, e) => s + (e.cluster_count || 0), 0);

  return (
    <div className="page">
      <div className="container">
        {/* Header */}
        <div className="flex items-center justify-between mb-8" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 style={{ marginBottom: '0.25rem' }}>My Events</h2>
            <p className="text-secondary text-sm">Manage your photo events and clusters</p>
          </div>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={16} /> New Event
          </button>
        </div>

        {/* Stats */}
        <div className="grid-3 mb-8" style={{ gap: '1rem' }}>
          {[
            { icon: Calendar,     label: 'Total Events',   value: events.length },
            { icon: Image,        label: 'Total Photos',   value: totalPhotos.toLocaleString() },
            { icon: Users,        label: 'Face Groups',    value: totalClusters },
          ].map(({ icon: Icon, label, value }) => (
            <div key={label} className="stat-card">
              <div className="flex items-center gap-2 text-muted mb-1">
                <Icon size={14} /> <span className="stat-label">{label}</span>
              </div>
              <div className="stat-value">{value}</div>
            </div>
          ))}
        </div>

        {/* Events grid */}
        {loading ? (
          <div className="flex justify-center" style={{ padding: '4rem' }}>
            <Loader2 size={32} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
          </div>
        ) : events.length === 0 ? (
          <motion.div
            className="card text-center"
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            style={{ padding: '4rem 2rem' }}
          >
            <Calendar size={48} color="var(--text-muted)" style={{ margin: '0 auto 1rem' }} />
            <h3 style={{ marginBottom: '0.5rem' }}>No events yet</h3>
            <p className="text-secondary text-sm" style={{ marginBottom: '1.5rem' }}>Create your first event to start uploading photos</p>
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              <Plus size={16} /> Create First Event
            </button>
          </motion.div>
        ) : (
          <div className="grid-2" style={{ gap: '1.25rem' }}>
            {events.map((event, idx) => (
              <motion.div
                key={event.id}
                className="event-card"
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.06 }}
                onClick={() => {}}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className={`badge ${event.is_active ? 'badge-active' : 'badge-failed'}`}>
                    {event.is_active ? '● Active' : '○ Inactive'}
                  </span>
                  <span className="text-xs text-muted">{new Date(event.created_at).toLocaleDateString()}</span>
                </div>

                <h3 style={{ marginBottom: '0.25rem' }}>{event.name}</h3>
                {event.description && <p className="text-sm text-secondary" style={{ marginBottom: '0.875rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{event.description}</p>}

                {/* Stats row */}
                <div className="flex gap-4 mb-4" style={{ marginTop: '0.5rem' }}>
                  {[
                    { label: 'Photos',    value: event.photo_count },
                    { label: 'Done',      value: event.processed_count },
                    { label: 'Groups',    value: event.cluster_count },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div style={{ fontWeight: 700, fontSize: '1.125rem' }}>{value}</div>
                      <div className="text-xs text-muted">{label}</div>
                    </div>
                  ))}
                </div>

                {/* Processing progress */}
                {event.photo_count > 0 && (
                  <div className="mb-4">
                    <div className="usage-bar-label mb-1">
                      <span className="flex items-center gap-1">
                        {event.processed_count === event.photo_count
                          ? <CheckCircle2 size={12} color="var(--success)" />
                          : <Clock size={12} color="var(--warning)" />}
                        Processing
                      </span>
                      <span>{event.processed_count}/{event.photo_count}</span>
                    </div>
                    <div className="progress-bar">
                      <div className="progress-bar-fill" style={{ width: `${event.photo_count > 0 ? (event.processed_count / event.photo_count) * 100 : 0}%` }} />
                    </div>
                  </div>
                )}

                {/* Access code */}
                <div style={{
                  background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)',
                  padding: '0.625rem 0.875rem', display: 'flex', alignItems: 'center', gap: '0.5rem',
                  marginBottom: '1rem',
                }}>
                  <Key size={13} color="var(--accent-light)" />
                  <span className="text-xs text-muted">Access code:</span>
                  <code style={{ fontFamily: 'monospace', fontSize: '0.875rem', fontWeight: 700, color: 'var(--accent-light)', letterSpacing: '0.1em' }}>
                    {event.access_code}
                  </code>
                </div>

                <Link
                  to={`/events/${event.id}`}
                  className="btn btn-secondary w-full"
                  style={{ justifyContent: 'center' }}
                  onClick={e => e.stopPropagation()}
                >
                  Manage Event <ArrowRight size={14} />
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Create event modal */}
      <AnimatePresence>
        {showCreate && (
          <motion.div className="modal-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div className="modal" initial={{ scale: 0.93, y: 16 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.93, y: 16 }}>
              <div className="flex items-center justify-between mb-6">
                <h3>Create New Event</h3>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}><X size={16} /></button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {createError && <div style={{ color: 'var(--error)', fontSize: '0.875rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', padding: '0.75rem' }}>{createError}</div>}
                <div className="input-group">
                  <label className="input-label">Event Name *</label>
                  <input className="input" placeholder="e.g. Annual Conference 2026" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} />
                </div>
                <div className="input-group">
                  <label className="input-label">Description (optional)</label>
                  <textarea className="input" rows={3} placeholder="Brief description of the event…" value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} style={{ resize: 'vertical' }} />
                </div>
                <p className="text-xs text-muted">A unique access code will be generated automatically for attendees to join.</p>
                <div className="flex gap-3 mt-2">
                  <button className="btn btn-ghost w-full" onClick={() => setShowCreate(false)}>Cancel</button>
                  <button className="btn btn-primary w-full" onClick={createEvent} disabled={creating || !form.name.trim()}>
                    {creating ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> : <Plus size={15} />}
                    Create Event
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
