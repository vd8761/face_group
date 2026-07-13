import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, Loader2, AlertCircle, Mail, Lock, User, Key } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import ConsentModal from '../components/ConsentModal';
import FaceScanner from '../components/FaceScanner';
import api from '../api/client';

const STEPS = ['join', 'consent', 'scan'];

export default function AttendeeScan() {
  const { user, attendeeJoin } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState(user ? 'consent' : 'join');
  const [eventData, setEventData] = useState(null);
  const [scanId, setScanId] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');

  // Join form
  const [joinForm, setJoinForm] = useState({ access_code: '', email: '', password: '', full_name: '' });
  const [joining, setJoining] = useState(false);

  // Look up event by code first (to show event name in consent)
  const lookupEvent = async (code) => {
    try {
      // Attendee join also validates the code
      return true;
    } catch { return false; }
  };

  const handleJoin = async (e) => {
    e.preventDefault();
    setError('');
    setJoining(true);
    try {
      await attendeeJoin(joinForm.access_code, joinForm.email, joinForm.password, joinForm.full_name);
      setEventData({ access_code: joinForm.access_code, name: `Event #${joinForm.access_code}` });
      setStep('consent');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid access code or credentials');
    } finally { setJoining(false); }
  };

  const handleConsentAccept = async () => {
    try {
      // Fetch event by access code to get event ID
      // For now, we store event context from join
      setStep('scan');
    } catch (e) { console.error(e); }
  };

  const handleScan = async (selfieFile) => {
    setScanning(true); setError('');
    try {
      // Get event ID from the attendee token (via /api/events endpoint with access code)
      // For the scan, we need the event ID — fetch it using the stored access code
      const user_data = JSON.parse(localStorage.getItem('pg_user') || '{}');

      // Fetch events accessible to this attendee tenant to find the matching event
      // (Attendees are scoped to one event via access code — get event by code)
      const eventsRes = await api.get('/api/events/');
      const events = eventsRes.data;

      let targetEventId = events[0]?.id; // Default to first accessible event

      if (!targetEventId) {
        throw new Error('No active event found for your account');
      }

      // Record consent
      await api.post('/api/faces/consent', {
        event_id: targetEventId,
        purpose: 'Face recognition to find photos I appear in at this event',
        accepted: true,
      });

      // Submit selfie scan
      const formData = new FormData();
      formData.append('selfie', selfieFile);
      const { data } = await api.post(`/api/faces/events/${targetEventId}/scan`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setScanId(data.scan_id);

      // Navigate to gallery with results
      navigate('/gallery', { state: { scanResult: data, eventId: targetEventId } });
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Scan failed. Please try again.');
    } finally { setScanning(false); }
  };

  return (
    <div className="hero-bg" style={{ flex: 1 }}>
      <div style={{ maxWidth: 520, margin: '0 auto', padding: '3rem 1.5rem' }}>
        {/* Header */}
        <motion.div className="text-center mb-8" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div style={{
            width: 60, height: 60,
            background: 'linear-gradient(135deg,var(--accent),var(--accent-light))',
            borderRadius: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 1.25rem', boxShadow: '0 8px 32px var(--accent-glow)',
          }}>
            <Camera size={28} color="#fff" strokeWidth={2.5} />
          </div>
          <h1 style={{ fontSize: '1.875rem', marginBottom: '0.5rem' }}>Find My Photos</h1>
          <p className="text-secondary">Scan your face to find every photo you appear in</p>
        </motion.div>

        {/* Step indicator */}
        <div className="flex justify-center gap-2 mb-8">
          {['Join Event', 'Consent', 'Scan'].map((label, i) => {
            const stepId = STEPS[i];
            const isActive = step === stepId;
            const isDone   = STEPS.indexOf(step) > i;
            return (
              <div key={label} className="flex items-center gap-2">
                <div style={{
                  width: 28, height: 28, borderRadius: '50%',
                  background: isDone ? 'var(--success)' : isActive ? 'var(--accent)' : 'var(--color-surface-2)',
                  border: `2px solid ${isDone ? 'var(--success)' : isActive ? 'var(--accent)' : 'var(--color-border)'}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '0.75rem', fontWeight: 700, color: isDone || isActive ? '#fff' : 'var(--text-muted)',
                  transition: 'all 0.3s',
                }}>
                  {isDone ? '✓' : i + 1}
                </div>
                <span className="text-xs" style={{ color: isActive ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: isActive ? 600 : 400 }}>{label}</span>
                {i < 2 && <div style={{ width: 24, height: 1, background: 'var(--color-border)', margin: '0 4px' }} />}
              </div>
            );
          })}
        </div>

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.75rem 1rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', marginBottom: '1.25rem' }}
            >
              <AlertCircle size={16} color="var(--error)" />
              <span className="text-sm" style={{ color: 'var(--error)' }}>{error}</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step: Join */}
        <AnimatePresence mode="wait">
          {step === 'join' && (
            <motion.div key="join" className="card" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <h3 style={{ marginBottom: '1.25rem' }}>Enter Event Details</h3>
              <form onSubmit={handleJoin} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div className="input-group">
                  <label className="input-label">Event Access Code</label>
                  <div style={{ position: 'relative' }}>
                    <Key size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                    <input className="input" required placeholder="e.g. AB12CD34" value={joinForm.access_code} onChange={e => setJoinForm(p => ({ ...p, access_code: e.target.value.toUpperCase() }))} style={{ paddingLeft: '2.5rem', fontFamily: 'monospace', letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700 }} />
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">Your Name</label>
                  <div style={{ position: 'relative' }}>
                    <User size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                    <input className="input" placeholder="Jane Doe" value={joinForm.full_name} onChange={e => setJoinForm(p => ({ ...p, full_name: e.target.value }))} style={{ paddingLeft: '2.5rem' }} />
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">Email</label>
                  <div style={{ position: 'relative' }}>
                    <Mail size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                    <input className="input" type="email" required placeholder="jane@example.com" value={joinForm.email} onChange={e => setJoinForm(p => ({ ...p, email: e.target.value }))} style={{ paddingLeft: '2.5rem' }} />
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">Create a Password</label>
                  <div style={{ position: 'relative' }}>
                    <Lock size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                    <input className="input" type="password" required placeholder="••••••••" value={joinForm.password} onChange={e => setJoinForm(p => ({ ...p, password: e.target.value }))} style={{ paddingLeft: '2.5rem' }} />
                  </div>
                </div>
                <button type="submit" className="btn btn-primary w-full" style={{ justifyContent: 'center', marginTop: '0.25rem' }} disabled={joining}>
                  {joining ? <><Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> Joining…</> : 'Join Event →'}
                </button>
              </form>
            </motion.div>
          )}

          {/* Step: Consent */}
          {step === 'consent' && (
            <motion.div key="consent" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <ConsentModal
                eventName={eventData?.name || 'Your Event'}
                onAccept={handleConsentAccept}
                onDecline={() => setStep('join')}
              />
            </motion.div>
          )}

          {/* Step: Scan */}
          {step === 'scan' && (
            <motion.div key="scan" className="card" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
              <h3 style={{ marginBottom: '0.375rem' }}>Scan Your Face</h3>
              <p className="text-sm text-secondary" style={{ marginBottom: '1.25rem' }}>
                Look directly at the camera. Make sure your face is well-lit and clearly visible.
              </p>
              <FaceScanner onCapture={handleScan} loading={scanning} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
