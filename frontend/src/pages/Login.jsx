import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Camera, Mail, Lock, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem 1.5rem', minHeight: '80vh' }}>
      <motion.div
        style={{ width: '100%', maxWidth: 440 }}
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        {/* Header */}
        <div className="text-center mb-8">
          <div style={{
            width: 56, height: 56,
            background: 'linear-gradient(135deg, var(--accent), var(--accent-light))',
            borderRadius: '16px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 1.25rem',
            boxShadow: '0 8px 32px var(--accent-glow)',
          }}>
            <Camera size={26} color="#fff" strokeWidth={2.5} />
          </div>
          <h1 style={{ fontSize: '1.75rem', marginBottom: '0.5rem' }}>Welcome back</h1>
          <p className="text-secondary">Sign in to PhotoGroup</p>
        </div>

        {/* Card */}
        <div className="card" style={{ padding: '2rem' }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Error */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.625rem',
                  padding: '0.75rem 1rem',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.2)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <AlertCircle size={16} color="var(--error)" />
                <span className="text-sm" style={{ color: 'var(--error)' }}>{error}</span>
              </motion.div>
            )}

            {/* Email */}
            <div className="input-group">
              <label className="input-label">Email address</label>
              <div style={{ position: 'relative' }}>
                <Mail size={16} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                <input
                  className="input"
                  type="email"
                  required
                  placeholder="you@example.com"
                  value={form.email}
                  onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                  style={{ paddingLeft: '2.5rem' }}
                />
              </div>
            </div>

            {/* Password */}
            <div className="input-group">
              <label className="input-label">Password</label>
              <div style={{ position: 'relative' }}>
                <Lock size={16} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                <input
                  className="input"
                  type={showPwd ? 'text' : 'password'}
                  required
                  placeholder="••••••••"
                  value={form.password}
                  onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                  style={{ paddingLeft: '2.5rem', paddingRight: '2.75rem' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(v => !v)}
                  style={{ position: 'absolute', right: '0.875rem', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}
                >
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button type="submit" className="btn btn-primary w-full" style={{ marginTop: '0.25rem', justifyContent: 'center' }} disabled={loading}>
              {loading ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Signing in…</> : 'Sign In'}
            </button>
          </form>

          <div className="divider" />

          <p className="text-center text-sm text-muted">
            Attendee?{' '}
            <Link to="/scan" style={{ color: 'var(--accent-light)', fontWeight: 600, textDecoration: 'none' }}>
              Find your photos →
            </Link>
          </p>
        </div>

        <p className="text-center text-xs text-muted mt-6">
          Organizations are provisioned by the platform admin only.
        </p>
      </motion.div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
