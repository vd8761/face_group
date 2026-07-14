import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Mail, Lock, Eye, EyeOff, AlertCircle, Loader2, ArrowRight, Camera, Shield, Zap } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import logo from '../assets/logo.png';

const floatingFeatures = [
  { icon: Camera, text: 'AI Face Grouping', sub: 'Powered by InsightFace' },
  { icon: Shield, text: 'Privacy First',    sub: 'GDPR & DPDP Compliant' },
  { icon: Zap,    text: 'Instant Results',  sub: 'Face match in < 3s' },
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [focused, setFocused] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const user = await login(form.email, form.password);
      if (user.role === 'super_admin') navigate('/admin');
      else if (user.role === 'organizer') navigate('/dashboard');
      else navigate('/scan');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      flex: 1, display: 'flex', minHeight: 'calc(100vh - 64px)',
      background: 'var(--color-bg)',
    }}>
      {/* ── Left panel — branding ── */}
      <motion.div
        initial={{ opacity: 0, x: -30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.6 }}
        style={{
          flex: '0 0 45%', display: 'flex', flexDirection: 'column',
          justifyContent: 'center', padding: '2rem 3rem',
          background: '#0f172a', /* Deep Slate/Midnight */
          position: 'relative', overflow: 'hidden',
        }}
        className="login-left-panel"
      >
        {/* Decorative subtle glows */}
        <div style={{
          position: 'absolute', width: 600, height: 600, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(79, 70, 229, 0.15) 0%, transparent 70%)',
          top: -200, right: -200, pointerEvents: 'none',
        }} />
        <div style={{
          position: 'absolute', width: 500, height: 500, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(6, 182, 212, 0.1) 0%, transparent 70%)',
          bottom: -150, left: -150, pointerEvents: 'none',
        }} />

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '2rem', position: 'relative', zIndex: 1 }}>
          <img src={logo} alt="UrFace AI Logo" style={{ height: 40, objectFit: 'contain' }} />
        </div>

        {/* Headline */}
        <div style={{ position: 'relative', zIndex: 1, marginBottom: '2rem' }}>
          <h2 style={{
            color: '#fff', fontSize: 'clamp(1.75rem, 3vw, 2.5rem)',
            lineHeight: 1.2, marginBottom: '1rem', fontWeight: 800,
          }}>
            Welcome to<br />
            <span style={{ background: 'linear-gradient(90deg, #22d3ee, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
              UrFace AI
            </span>
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.95rem', lineHeight: 1.5, maxWidth: 320 }}>
            Upload event photos, manage clusters, and share access codes — all in one place.
          </p>
        </div>

        {/* Feature chips */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem', position: 'relative', zIndex: 1 }}>
          {floatingFeatures.map(({ icon: Icon, text, sub }, i) => (
            <motion.div
              key={text}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 + i * 0.12 }}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.75rem',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.05)',
                borderRadius: '12px', padding: '0.75rem 1rem',
                backdropFilter: 'blur(10px)',
              }}
            >
              <div style={{ width: 38, height: 38, borderRadius: '10px', background: 'rgba(255,255,255,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Icon size={17} color="rgba(255,255,255,0.9)" />
              </div>
              <div>
                <div style={{ color: '#fff', fontSize: '0.875rem', fontWeight: 600 }}>{text}</div>
                <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.75rem' }}>{sub}</div>
              </div>
            </motion.div>
          ))}
        </div>
      </motion.div>

      {/* ── Right panel — form ── */}
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '2rem 1.5rem',
      }}>
        <motion.div
          style={{ width: '100%', maxWidth: 420 }}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15 }}
        >
          {/* Greeting */}
          <div style={{ marginBottom: '2rem' }}>
            <h1 style={{ fontSize: '1.75rem', marginBottom: '0.375rem', fontWeight: 800 }}>Welcome back 👋</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Sign in to manage your events and photos
            </p>
          </div>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8, height: 0 }}
                animate={{ opacity: 1, y: 0, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.625rem',
                  padding: '0.875rem 1rem', marginBottom: '1.25rem',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.25)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <AlertCircle size={16} color="var(--error)" />
                <span style={{ fontSize: '0.875rem', color: 'var(--error)', fontWeight: 500 }}>{error}</span>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.125rem' }}>
            {/* Email */}
            <div className="input-group">
              <label className="input-label" style={{ fontWeight: 600, fontSize: '0.8rem', letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Email address
              </label>
              <div style={{ position: 'relative' }}>
                <Mail
                  size={15}
                  color={focused === 'email' ? 'var(--accent)' : 'var(--text-muted)'}
                  style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', transition: 'color 0.2s' }}
                />
                <input
                  className="input"
                  type="email"
                  required
                  placeholder="you@example.com"
                  value={form.email}
                  onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                  onFocus={() => setFocused('email')}
                  onBlur={() => setFocused('')}
                  style={{ paddingLeft: '2.75rem', height: '52px', fontSize: '0.9375rem' }}
                />
              </div>
            </div>

            {/* Password */}
            <div className="input-group">
              <label className="input-label" style={{ fontWeight: 600, fontSize: '0.8rem', letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Password
              </label>
              <div style={{ position: 'relative' }}>
                <Lock
                  size={15}
                  color={focused === 'password' ? 'var(--accent)' : 'var(--text-muted)'}
                  style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', transition: 'color 0.2s' }}
                />
                <input
                  className="input"
                  type={showPwd ? 'text' : 'password'}
                  required
                  placeholder="••••••••••"
                  value={form.password}
                  onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                  onFocus={() => setFocused('password')}
                  onBlur={() => setFocused('')}
                  style={{ paddingLeft: '2.75rem', paddingRight: '3rem', height: '52px', fontSize: '0.9375rem' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(v => !v)}
                  style={{
                    position: 'absolute', right: '1rem', top: '50%', transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', padding: '0.25rem', borderRadius: '6px',
                    transition: 'color 0.2s',
                  }}
                >
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary"
              style={{
                width: '100%', justifyContent: 'center', padding: '0.875rem',
                fontSize: '1rem', marginTop: '1.5rem',
              }}
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : 'Sign In'}
              {!loading && <ArrowRight size={16} />}
            </button>
          </form>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', margin: '1.75rem 0' }}>
            <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Not an organizer?</span>
            <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
          </div>

          {/* Attendee CTA */}
          <Link
            to="/scan"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
              padding: '0.875rem 1.5rem', borderRadius: 'var(--radius-lg)',
              background: 'var(--accent-soft)', border: '1px solid rgba(124,58,237,0.25)',
              color: 'var(--accent-light)', fontWeight: 600, fontSize: '0.9375rem',
              textDecoration: 'none', transition: 'all 0.2s',
            }}
          >
            <Camera size={17} />
            Find My Photos as Attendee
            <ArrowRight size={15} />
          </Link>

          <p style={{ textAlign: 'center', fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '1.5rem' }}>
            Organizations are provisioned by the platform admin only.
          </p>
        </motion.div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 768px) {
          .login-left-panel { display: none !important; }
        }
      `}</style>
    </div>
  );
}
