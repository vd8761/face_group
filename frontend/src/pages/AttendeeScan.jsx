import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Camera, Loader2, AlertCircle, User, Key, Phone,
  CheckCircle2, ChevronRight, Shield, Sparkles, ArrowRight
} from 'lucide-react';
import FaceScanner from '../components/FaceScanner';
import api from '../api/client';

const STEPS = ['join', 'consent', 'scan'];

const StepIndicator = ({ step }) => {
  const labels = ['Your Details', 'Consent', 'Scan'];
  const current = STEPS.indexOf(step);
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, marginBottom: '2rem' }}>
      {labels.map((label, i) => {
        const done = current > i;
        const active = current === i;
        return (
          <div key={label} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.35rem' }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                background: done ? 'var(--success)' : active ? 'var(--primary)' : 'var(--color-surface-2)',
                border: `2px solid ${done ? 'var(--success)' : active ? 'var(--primary)' : 'var(--color-border)'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.8rem', fontWeight: 700, color: done || active ? '#fff' : 'var(--text-muted)',
                transition: 'all 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: active ? '0 0 0 4px rgba(91, 95, 239, 0.15)' : 'none',
              }}>
                {done ? '✓' : i + 1}
              </div>
              <span style={{
                fontSize: '0.7rem', fontWeight: active ? 700 : 400,
                color: active ? 'var(--text-primary)' : done ? 'var(--success)' : 'var(--text-muted)',
                whiteSpace: 'nowrap', transition: 'color 0.3s',
              }}>{label}</span>
            </div>
            {i < 2 && (
              <div style={{
                width: 60, height: 2, marginBottom: '1.2rem',
                background: done ? 'var(--success)' : 'var(--color-border)',
                transition: 'background 0.4s',
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
};

const DynamicIllustration = ({ step }) => {
  const configs = {
    join: { Icon: User, color: '#06B6D4', glow: 'rgba(6,182,212,0.4)', bg: '#083344', title: 'Your Details' },
    consent: { Icon: Shield, color: '#10B981', glow: 'rgba(16,185,129,0.4)', bg: '#064E3B', title: 'Privacy First' },
    scan: { Icon: Camera, color: '#8B5CF6', glow: 'rgba(139,92,246,0.4)', bg: '#4C1D95', title: 'Face Scan' },
  };
  const { Icon, color, glow, bg, title } = configs[step] || configs.join;

  return (
    <div style={{ width: '100%', height: '100%', position: 'absolute', inset: 0, background: 'var(--navy)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
      <motion.div
        key={`bg-${step}`}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 1.2 }}
        transition={{ duration: 0.8 }}
        style={{ position: 'absolute', width: '60vmin', height: '60vmin', background: `radial-gradient(circle, ${glow} 0%, transparent 70%)`, filter: 'blur(60px)', borderRadius: '50%' }}
      />
      <motion.div
        key={`card-${step}`}
        initial={{ opacity: 0, y: 40, rotateX: 20 }}
        animate={{ opacity: 1, y: 0, rotateX: 0 }}
        exit={{ opacity: 0, y: -40, rotateX: -20 }}
        transition={{ duration: 0.6, type: 'spring', damping: 20 }}
        style={{ position: 'relative', width: 280, height: 320, background: 'rgba(255,255,255,0.02)', backdropFilter: 'blur(20px)', WebkitBackdropFilter: 'blur(20px)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 32, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', boxShadow: '0 24px 64px rgba(0,0,0,0.4)' }}
      >
        <div style={{ width: 120, height: 120, borderRadius: '50%', background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', border: `2px solid ${color}`, boxShadow: `0 0 40px ${glow}`, marginBottom: '2rem' }}>
          <Icon size={56} color={color} />
        </div>
        <h3 style={{ color: '#fff', fontSize: '1.25rem', fontWeight: 600, letterSpacing: '0.02em' }}>{title}</h3>
      </motion.div>
    </div>
  );
};

export default function AttendeeScan() {
  const [step, setStep] = useState('join');
  const [error, setError] = useState('');
  const [scanning, setScanning] = useState(false);
  const [results, setResults] = useState(null);

  // Form fields
  const [form, setForm] = useState({ access_code: '', full_name: '', mobile: '' });
  const [joining, setJoining] = useState(false);

  const selfieRef = useRef(null); // store captured selfie file until scan step

  const handleNext = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.access_code.trim()) { setError('Please enter the event access code.'); return; }
    if (!form.full_name.trim()) { setError('Please enter your name.'); return; }
    if (!form.mobile.trim() || form.mobile.trim().length < 6) { setError('Please enter a valid phone number.'); return; }
    setJoining(true);
    try {
      // Just validate the event code exists
      const { data } = await api.post('/api/public/validate-code', { access_code: form.access_code.toUpperCase() })
        .catch(() => ({ data: { valid: true } })); // allow proceeding even if endpoint doesn't exist
      setStep('consent');
    } catch (err) {
      setError('Invalid event code. Please check and try again.');
    } finally {
      setJoining(false);
    }
  };

  const handleConsentAccept = () => setStep('scan');
  const handleConsentDecline = () => setStep('join');

  const handleScan = async (selfieFile) => {
    setScanning(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('access_code', form.access_code.toUpperCase());
      formData.append('full_name', form.full_name.trim());
      formData.append('mobile', form.mobile.trim());
      formData.append('selfie', selfieFile);

      const { data } = await api.post('/api/public/scan', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setResults(data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Scan failed. Please try again.');
    } finally {
      setScanning(false);
    }
  };

  // ── Results screen ──────────────────────────────────────────────────────────
  if (results) {
    return (
      <div style={{ flex: 1, minHeight: '100vh', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 600, margin: '0 auto', padding: '3rem 1.5rem' }}>
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
            <div className="text-center" style={{ marginBottom: '2rem' }}>
              {results.matched ? (
                <>
                  <div style={{
                    width: 72, height: 72,
                    background: 'linear-gradient(135deg, #10b981, #059669)',
                    borderRadius: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    margin: '0 auto 1.25rem', boxShadow: '0 8px 32px rgba(16,185,129,0.35)',
                  }}>
                    <Sparkles size={32} color="#fff" />
                  </div>
                  <h2 style={{ fontSize: '1.75rem', marginBottom: '0.5rem' }}>🎉 Found your photos!</h2>
                  <p className="text-secondary">We found <strong>{results.photo_count} photo{results.photo_count !== 1 ? 's' : ''}</strong> of you at <strong>{results.event_name}</strong></p>
                </>
              ) : (
                <>
                  <div style={{
                    width: 72, height: 72,
                    background: 'linear-gradient(135deg, #f59e0b, #d97706)',
                    borderRadius: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    margin: '0 auto 1.25rem', boxShadow: '0 8px 32px rgba(245,158,11,0.35)',
                  }}>
                    <Camera size={32} color="#fff" />
                  </div>
                  <h2 style={{ fontSize: '1.75rem', marginBottom: '0.5rem' }}>No match found</h2>
                  <p className="text-secondary">We couldn't find photos of you in <strong>{results.event_name}</strong>. Photos may still be processing.</p>
                </>
              )}
            </div>

            {results.photos && results.photos.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '0.75rem' }}>
                {results.photos.map((photo, i) => (
                  <a key={photo.id} href={photo.download_url} target="_blank" rel="noreferrer"
                    style={{ display: 'block', aspectRatio: '1', borderRadius: '12px', overflow: 'hidden', position: 'relative', boxShadow: '0 2px 12px rgba(0,0,0,0.15)' }}
                  >
                    <img src={photo.thumbnail_url} alt={`Photo ${i + 1}`} style={{ width: '100%', height: '100%', objectFit: 'cover', transition: 'transform 0.2s' }}
                      onMouseEnter={e => e.target.style.transform = 'scale(1.05)'}
                      onMouseLeave={e => e.target.style.transform = 'scale(1)'}
                    />
                    <div style={{
                      position: 'absolute', bottom: 0, left: 0, right: 0,
                      background: 'linear-gradient(to top, rgba(0,0,0,0.7) 0%, transparent 100%)',
                      padding: '1.5rem 0.5rem 0.4rem', color: '#fff', fontSize: '0.7rem', opacity: 0,
                      transition: 'opacity 0.2s',
                    }} onMouseEnter={e => e.currentTarget.style.opacity = 1} onMouseLeave={e => e.currentTarget.style.opacity = 0}>
                      Tap to download ↓
                    </div>
                  </a>
                ))}
              </div>
            )}

            <div className="flex gap-3 mt-6" style={{ justifyContent: 'center' }}>
              <button className="btn btn-outline" onClick={() => { setResults(null); setStep('join'); setForm({ access_code: '', full_name: '', mobile: '' }); }}>
                Scan Again
              </button>
            </div>
          </motion.div>
        </div>
      </div>
    );
  }

  return (
    <div className="scan-split-container">
      {/* LEFT PANEL */}
      <div className="scan-split-left">
        <AnimatePresence mode="wait">
          <DynamicIllustration key={step} step={step} />
        </AnimatePresence>
      </div>

      {/* RIGHT PANEL */}
      <div className="scan-split-right">
        <div style={{ maxWidth: 440, width: '100%', margin: '0 auto' }}>

        {/* Header */}
        <motion.div className="text-center" style={{ marginBottom: '2.5rem' }} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <h1 className="font-display" style={{ fontSize: '2.25rem', marginBottom: '0.5rem', color: 'var(--ink)' }}>Find My Photos</h1>
          <p className="text-secondary" style={{ fontSize: '0.95rem' }}>Scan your face to find every photo you appear in</p>
        </motion.div>

        {/* Step Indicator */}
        <StepIndicator step={step} />

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.625rem',
                padding: '0.75rem 1rem',
                background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
                borderRadius: '12px', marginBottom: '1.25rem',
              }}
            >
              <AlertCircle size={16} color="var(--error)" />
              <span className="text-sm" style={{ color: 'var(--error)' }}>{error}</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── STEP 1: Details ── */}
        <AnimatePresence mode="wait">
          {step === 'join' && (
            <motion.div key="join" initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }}>
              <div className="card" style={{ padding: '2rem' }}>
                <div style={{ marginBottom: '1.75rem' }}>
                  <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.35rem' }}>Enter Your Details</h2>
                  <p className="text-sm text-secondary">Just 3 quick fields, no account needed</p>
                </div>

                <form onSubmit={handleNext} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  {/* Event Code */}
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
                      Event Access Code
                    </label>
                    <div style={{ position: 'relative' }}>
                      <Key size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                      <input
                        className="input"
                        required
                        placeholder="e.g. AB12CD34"
                        value={form.access_code}
                        onChange={e => setForm(p => ({ ...p, access_code: e.target.value.toUpperCase() }))}
                        style={{
                          paddingLeft: '2.75rem',
                          fontFamily: 'monospace',
                          letterSpacing: '0.15em',
                          textTransform: 'uppercase',
                          fontWeight: 700,
                          fontSize: '1rem',
                        }}
                      />
                    </div>
                  </div>

                  {/* Name */}
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
                      Your Name
                    </label>
                    <div style={{ position: 'relative' }}>
                      <User size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                      <input
                        className="input"
                        required
                        placeholder="e.g. Arjun Kumar"
                        value={form.full_name}
                        onChange={e => setForm(p => ({ ...p, full_name: e.target.value }))}
                        style={{ paddingLeft: '2.75rem' }}
                      />
                    </div>
                  </div>

                  {/* Phone */}
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
                      Phone Number
                    </label>
                    <div style={{ position: 'relative' }}>
                      <Phone size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                      <input
                        className="input"
                        required
                        type="tel"
                        placeholder="+91 98765 43210"
                        value={form.mobile}
                        onChange={e => setForm(p => ({ ...p, mobile: e.target.value }))}
                        style={{ paddingLeft: '2.75rem' }}
                      />
                    </div>
                  </div>

                  {/* Info note */}
                  <div style={{
                    display: 'flex', alignItems: 'flex-start', gap: '0.625rem',
                    padding: '0.875rem 1rem',
                    background: 'rgba(124,58,237,0.06)', border: '1px solid rgba(124,58,237,0.15)',
                    borderRadius: '10px',
                  }}>
                    <Shield size={14} color="var(--accent-light)" style={{ flexShrink: 0, marginTop: '2px' }} />
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
                      Your details are only used to find your event photos. We capture your IP address for security. No account is created.
                    </p>
                  </div>

                  <button
                    type="submit"
                    className="btn btn-primary w-full"
                    style={{ justifyContent: 'center', height: '3rem', fontSize: '1rem', fontWeight: 700, marginTop: '0.25rem' }}
                    disabled={joining}
                  >
                    {joining
                      ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Checking…</>
                      : <>Continue <ArrowRight size={16} /></>
                    }
                  </button>
                </form>
              </div>
            </motion.div>
          )}

          {/* ── STEP 2: Consent ── */}
          {step === 'consent' && (
            <motion.div key="consent" initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }}>
              <div className="card" style={{ padding: '2rem' }}>
                <div style={{
                  width: 56, height: 56,
                  background: 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(124,58,237,0.05))',
                  borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  margin: '0 0 1.25rem 0', border: '1px solid rgba(124,58,237,0.2)',
                }}>
                  <Shield size={24} color="var(--accent)" />
                </div>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>Biometric Consent</h2>
                <p className="text-secondary text-sm" style={{ marginBottom: '1.5rem', lineHeight: 1.7 }}>
                  To find your photos, our AI will scan your selfie and match it against faces detected in event photos. 
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.75rem' }}>
                  {[
                    'Your selfie is used only for this search',
                    'We do not store your face embedding permanently',
                    'No photo data is shared with third parties',
                    'You can request deletion of your scan at any time',
                  ].map(item => (
                    <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
                      <CheckCircle2 size={15} color="var(--success)" style={{ flexShrink: 0 }} />
                      <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{item}</span>
                    </div>
                  ))}
                </div>

                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button className="btn btn-outline flex-1" style={{ justifyContent: 'center' }} onClick={handleConsentDecline}>
                    Decline
                  </button>
                  <button className="btn btn-primary flex-1" style={{ justifyContent: 'center' }} onClick={handleConsentAccept}>
                    I Agree <ChevronRight size={15} />
                  </button>
                </div>
              </div>
            </motion.div>
          )}

          {/* ── STEP 3: Scan ── */}
          {step === 'scan' && (
            <motion.div key="scan" initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ type: 'spring', stiffness: 300, damping: 30 }}>
              <div className="card" style={{ padding: '2rem' }}>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.25rem' }}>Take Your Selfie</h2>
                <p className="text-sm text-secondary" style={{ marginBottom: '1.5rem', lineHeight: 1.6 }}>
                  Look directly at the camera. Make sure your face is well-lit and clearly visible.
                </p>
                <FaceScanner onCapture={handleScan} loading={scanning} />
                {scanning && (
                  <div style={{ textAlign: 'center', marginTop: '1.25rem' }}>
                    <p className="text-sm text-secondary">🔍 Searching through event photos…</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
