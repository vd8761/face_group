import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus, Calendar, Image, Users, CheckCircle2, Clock,
  X, ArrowRight, Loader2, Key, Copy, Check, Sparkles,
  TrendingUp, Camera, Activity
} from 'lucide-react';
import api from '../api/client';

function copyToClipboard(text, setCopied) {
  navigator.clipboard.writeText(text).then(() => {
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  });
}

export default function OrganizerDashboard() {
  const [events, setEvents]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm]       = useState({ name: '', description: '' });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/events/');
      setEvents(res.data);
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
  const totalDone     = events.reduce((s, e) => s + (e.processed_count || 0), 0);

  return (
    <div style={{ flex: 1, background: 'var(--color-bg)', minHeight: '100vh' }}>
      <div style={{
        background: 'linear-gradient(135deg, rgba(79, 70, 229, 0.08) 0%, rgba(6, 182, 212, 0.06) 100%)',
        borderBottom: '1px solid var(--color-border)',
        padding: '2rem 0',
      }}>
        <div className="container">
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', marginBottom: '0.375rem' }}>
                <div style={{
                  width: 36, height: 36, borderRadius: '10px',
                  background: 'linear-gradient(135deg,#4f46e5,#06b6d4)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Camera size={18} color="#fff" />
                </div>
                <h2 style={{ margin: 0, fontSize: '1.75rem' }}>My Events</h2>
              </div>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', margin: 0 }}>
                Manage photo events, uploads, and face recognition clusters
              </p>
            </div>
            <button
              className="btn btn-primary"
              onClick={() => setShowCreate(true)}
              style={{ gap: '0.5rem', padding: '0.75rem 1.5rem', fontSize: '0.95rem' }}
            >
              <Plus size={17} /> New Event
            </button>
          </div>
        </div>
      </div>

      <div className="container" style={{ padding: '2rem 1.5rem' }}>
        {/* Stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
          {[
            { icon: Calendar,   label: 'Total Events',     value: events.length,               color: '#4f46e5', bg: 'rgba(79, 70, 229, 0.1)' },
            { icon: Image,      label: 'Total Photos',     value: totalPhotos.toLocaleString(), color: '#0ea5e9', bg: 'rgba(14, 165, 233, 0.1)' },
            { icon: CheckCircle2, label: 'Processed',      value: totalDone.toLocaleString(),   color: '#16a34a', bg: 'rgba(22, 163, 74, 0.1)' },
            { icon: Users,      label: 'Face Groups',      value: totalClusters,                color: '#06b6d4', bg: 'rgba(6, 182, 212, 0.1)' },
          ].map(({ icon: Icon, label, value, color, bg }, i) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.07 }}
              style={{
                background: '#fff',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-lg)',
                padding: '1.25rem 1.5rem',
                boxShadow: 'var(--shadow-sm)',
                display: 'flex', alignItems: 'center', gap: '1rem',
              }}
            >
              <div style={{ width: 44, height: 44, borderRadius: '12px', background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Icon size={20} color={color} />
              </div>
              <div>
                <div style={{ fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.03em', color: 'var(--text-primary)', lineHeight: 1 }}>{value}</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem', fontWeight: 500 }}>{label}</div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Section title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1.25rem' }}>
          <Activity size={15} color="var(--accent-light)" />
          <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
            {events.length} Event{events.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Events grid */}
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '5rem', gap: '0.75rem' }}>
            <Loader2 size={28} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
            <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>Loading events…</span>
          </div>
        ) : events.length === 0 ? (
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            style={{
              background: '#fff', border: '2px dashed var(--color-border)',
              borderRadius: 'var(--radius-xl)', padding: '5rem 2rem',
              textAlign: 'center',
            }}
          >
            <div style={{ width: 64, height: 64, background: 'var(--accent-soft)', borderRadius: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 1.25rem' }}>
              <Sparkles size={28} color="var(--accent-light)" />
            </div>
            <h3 style={{ marginBottom: '0.5rem', fontSize: '1.25rem' }}>No events yet</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1.75rem', maxWidth: 340, margin: '0 auto 1.75rem' }}>
              Create your first event to start uploading photos and enabling face recognition for your attendees.
            </p>
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              <Plus size={16} /> Create First Event
            </button>
          </motion.div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1.25rem' }}>
            {events.map((event, idx) => {
              const progress = event.photo_count > 0 ? (event.processed_count / event.photo_count) * 100 : 0;
              const isCopied = copiedId === event.id;
              return (
                <motion.div
                  key={event.id}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.06 }}
                  style={{
                    background: '#fff',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-xl)',
                    padding: '1.5rem',
                    boxShadow: 'var(--shadow-sm)',
                    display: 'flex', flexDirection: 'column', gap: '1rem',
                    transition: 'box-shadow 0.2s, border-color 0.2s',
                  }}
                  whileHover={{ boxShadow: '0 8px 32px rgba(124,58,237,0.10)', borderColor: 'rgba(124,58,237,0.25)' }}
                >
                  {/* Top row */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
                    <div>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                        background: event.is_active ? 'rgba(22,163,74,0.1)' : 'rgba(100,116,139,0.1)',
                        color: event.is_active ? '#16a34a' : 'var(--text-muted)',
                        border: `1px solid ${event.is_active ? 'rgba(22,163,74,0.25)' : 'rgba(100,116,139,0.2)'}`,
                        fontSize: '0.72rem', fontWeight: 700, padding: '0.2rem 0.6rem', borderRadius: '999px',
                        marginBottom: '0.625rem',
                      }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', display: 'inline-block' }} />
                        {event.is_active ? 'Active' : 'Inactive'}
                      </span>
                      <h3 style={{ margin: 0, fontSize: '1.05rem', lineHeight: 1.3 }}>{event.name}</h3>
                      {event.description && (
                        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: '0.25rem 0 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }}>
                          {event.description}
                        </p>
                      )}
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap', paddingTop: '0.15rem' }}>
                      {new Date(event.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </span>
                  </div>

                  {/* Stats chips */}
                  <div style={{ display: 'flex', gap: '0.625rem' }}>
                    {[
                      { label: 'Photos',  value: event.photo_count,     color: '#2563eb', bg: 'rgba(37,99,235,0.08)' },
                      { label: 'Done',    value: event.processed_count, color: '#16a34a', bg: 'rgba(22,163,74,0.08)' },
                      { label: 'Groups',  value: event.cluster_count,   color: '#7c3aed', bg: 'rgba(124,58,237,0.08)' },
                    ].map(({ label, value, color, bg }) => (
                      <div key={label} style={{ flex: 1, background: bg, borderRadius: 'var(--radius-md)', padding: '0.625rem 0.5rem', textAlign: 'center' }}>
                        <div style={{ fontSize: '1.2rem', fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
                        <div style={{ fontSize: '0.7rem', color, opacity: 0.75, marginTop: '0.2rem', fontWeight: 600 }}>{label}</div>
                      </div>
                    ))}
                  </div>

                  {/* Progress bar */}
                  {event.photo_count > 0 && (
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                          {progress === 100
                            ? <CheckCircle2 size={11} color="var(--success)" />
                            : <Clock size={11} color="var(--warning)" />}
                          Processing
                        </span>
                        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: progress === 100 ? 'var(--success)' : 'var(--text-secondary)' }}>
                          {event.processed_count}/{event.photo_count}
                        </span>
                      </div>
                      <div style={{ height: 6, background: 'var(--color-surface-2)', borderRadius: 999, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', width: `${progress}%`,
                          background: progress === 100
                            ? 'linear-gradient(90deg,#16a34a,#4ade80)'
                            : 'linear-gradient(90deg,#7c3aed,#ec4899)',
                          borderRadius: 999,
                          transition: 'width 0.6s ease',
                        }} />
                      </div>
                    </div>
                  )}

                  {/* Access code */}
                  <div
                    onClick={() => copyToClipboard(event.access_code, (v) => v && setCopiedId(event.id))}
                    style={{
                      background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)',
                      padding: '0.625rem 0.875rem', display: 'flex', alignItems: 'center',
                      justifyContent: 'space-between', cursor: 'pointer',
                      border: '1px solid var(--color-border)',
                      transition: 'border-color 0.2s',
                    }}
                    title="Click to copy access code"
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Key size={12} color="var(--accent-light)" />
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Access code</span>
                      <code style={{ fontFamily: 'monospace', fontSize: '0.875rem', fontWeight: 700, color: 'var(--accent-light)', letterSpacing: '0.08em' }}>
                        {event.access_code}
                      </code>
                    </div>
                    {isCopied
                      ? <Check size={13} color="var(--success)" />
                      : <Copy size={12} color="var(--text-muted)" />}
                  </div>

                  {/* CTA */}
                  <Link
                    to={`/events/${event.id}`}
                    className="btn btn-primary w-full"
                    style={{ justifyContent: 'center', marginTop: 'auto' }}
                  >
                    Manage Event <ArrowRight size={15} />
                  </Link>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* Create event modal */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            className="modal-overlay"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={(e) => e.target === e.currentTarget && setShowCreate(false)}
          >
            <motion.div
              className="modal"
              initial={{ scale: 0.94, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.94, y: 20, opacity: 0 }}
              style={{ maxWidth: 460 }}
            >
              {/* Modal header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                  <div style={{ width: 36, height: 36, borderRadius: '10px', background: 'var(--accent-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Sparkles size={16} color="var(--accent-light)" />
                  </div>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Create New Event</h3>
                    <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--text-muted)' }}>A unique access code will be auto-generated</p>
                  </div>
                </div>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}>
                  <X size={16} />
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {createError && (
                  <div style={{ color: 'var(--error)', fontSize: '0.875rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', padding: '0.75rem 1rem' }}>
                    {createError}
                  </div>
                )}
                <div className="input-group">
                  <label className="input-label">Event Name <span style={{ color: 'var(--error)' }}>*</span></label>
                  <input
                    className="input"
                    placeholder="e.g. Annual Conference 2026"
                    value={form.name}
                    onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && createEvent()}
                    autoFocus
                  />
                </div>
                <div className="input-group">
                  <label className="input-label">Description <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(optional)</span></label>
                  <textarea
                    className="input" rows={3}
                    placeholder="Brief description of the event…"
                    value={form.description}
                    onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
                    style={{ resize: 'vertical' }}
                  />
                </div>
                <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.25rem' }}>
                  <button className="btn btn-ghost" style={{ flex: 1, justifyContent: 'center' }} onClick={() => setShowCreate(false)}>
                    Cancel
                  </button>
                  <button
                    className="btn btn-primary"
                    style={{ flex: 2, justifyContent: 'center' }}
                    onClick={createEvent}
                    disabled={creating || !form.name.trim()}
                  >
                    {creating
                      ? <><Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> Creating…</>
                      : <><Plus size={15} /> Create Event</>}
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
