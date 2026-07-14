import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Mail, Lock, Eye, EyeOff, AlertCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Logo from '../components/Logo';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  const validate = () => {
    const newErrors = {};
    if (!form.email) newErrors.email = 'Please fill out this field.';
    if (!form.password) newErrors.password = 'Please fill out this field.';
    setFieldErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validate()) return;
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
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--color-bg)',
      minHeight: 'calc(100vh - 64px)',
      padding: '2rem 1.5rem'
    }}>
      <motion.div
        className="card"
        style={{ width: '100%', maxWidth: 420, padding: '2.5rem 2rem' }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        {/* Logo & Greeting */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: '2rem', textAlign: 'center' }}>
          <Logo align="center" style={{ marginBottom: '1rem' }} />
          <h1 className="font-display" style={{ fontSize: '1.75rem', marginBottom: '0.5rem', color: 'var(--ink)' }}>Sign in</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>
            Continue to Organizer Dashboard
          </p>
        </div>

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              style={{ overflow: 'hidden' }}
            >
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.625rem',
                padding: '0.75rem 1rem', marginBottom: '1.5rem',
                background: 'rgba(217,48,37,0.08)',
                border: '1px solid rgba(217,48,37,0.2)',
                borderRadius: 'var(--radius-sm)',
              }}>
                <AlertCircle size={16} color="var(--error)" />
                <span style={{ fontSize: '0.85rem', color: 'var(--error)', fontWeight: 500 }}>{error}</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Email */}
          <div>
            <div style={{ position: 'relative' }}>
              <input
                className="input"
                type="email"
                required
                placeholder="Email address"
                value={form.email}
                onChange={e => {
                  setForm(p => ({ ...p, email: e.target.value }));
                  if (fieldErrors.email) setFieldErrors(p => ({ ...p, email: '' }));
                }}
                style={{ 
                  padding: '0.875rem 1rem', 
                  height: 'auto', 
                  fontSize: '1rem', 
                  width: '100%',
                  borderColor: fieldErrors.email ? 'var(--error)' : undefined
                }}
              />
            </div>
            {fieldErrors.email && (
              <div style={{ color: 'var(--error)', fontSize: '0.85rem', marginTop: '0.375rem', fontWeight: 500 }}>
                {fieldErrors.email}
              </div>
            )}
          </div>

          {/* Password */}
          <div>
            <div style={{ position: 'relative' }}>
              <input
                className="input"
                type={showPwd ? 'text' : 'password'}
                required
                placeholder="Password"
                value={form.password}
                onChange={e => {
                  setForm(p => ({ ...p, password: e.target.value }));
                  if (fieldErrors.password) setFieldErrors(p => ({ ...p, password: '' }));
                }}
                style={{ 
                  padding: '0.875rem 3rem 0.875rem 1rem', 
                  height: 'auto', 
                  fontSize: '1rem', 
                  width: '100%',
                  borderColor: fieldErrors.password ? 'var(--error)' : undefined
                }}
              />
              <button
                type="button"
                onClick={() => setShowPwd(v => !v)}
                style={{
                  position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text-muted)', padding: '0.25rem',
                }}
              >
                {showPwd ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {fieldErrors.password && (
              <div style={{ color: 'var(--error)', fontSize: '0.85rem', marginTop: '0.375rem', fontWeight: 500 }}>
                {fieldErrors.password}
              </div>
            )}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{
              width: '100%', justifyContent: 'center', padding: '0.875rem',
              fontSize: '1rem', marginTop: '0.5rem', fontWeight: 600,
              borderRadius: 'var(--radius-sm)'
            }}
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : 'Sign in'}
          </button>
        </form>

        <div style={{ marginTop: '2rem', textAlign: 'center' }}>
          <Link to="/scan" className="btn btn-ghost" style={{ fontSize: '0.9rem', padding: '0.5rem 1rem' }}>
            Looking for attendee access?
          </Link>
        </div>
      </motion.div>
    </div>
  );
}
