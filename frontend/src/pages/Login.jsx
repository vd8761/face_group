import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Mail, Lock, Eye, EyeOff, AlertCircle, Loader2, ScanFace, Image as ImageIcon, Camera } from 'lucide-react';
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
    if (!form.email) newErrors.email = 'Required field.';
    if (!form.password) newErrors.password = 'Required field.';
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
    <div style={{ display: 'flex', height: 'calc(100vh - 68px)', width: '100%', background: '#fff', overflow: 'hidden' }}>
      
      {/* ── Left Side: Visual/Branding (Hidden on mobile) ── */}
      <div className="login-visual-panel" style={{
        flex: '1.2',
        position: 'relative',
        background: 'linear-gradient(135deg, #01233F 0%, #001222 100%)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '2rem 3rem',
        color: '#fff'
      }}>
        {/* Abstract decorative elements */}
        <div style={{ position: 'absolute', top: '-10%', right: '-10%', width: '50vw', height: '50vw', background: 'radial-gradient(circle, rgba(0, 163, 181, 0.35) 0%, transparent 60%)', filter: 'blur(60px)', borderRadius: '50%' }} />
        <div style={{ position: 'absolute', bottom: '-20%', left: '-10%', width: '60vw', height: '60vw', background: 'radial-gradient(circle, rgba(255, 123, 0, 0.25) 0%, transparent 70%)', filter: 'blur(80px)', borderRadius: '50%' }} />
        
        {/* Animated Brand Graphic - Unique & Thematic */}
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
          <div style={{ position: 'relative', width: 400, height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            
            {/* Center Face/Scan Icon */}
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              style={{
                width: 120, height: 120, borderRadius: '50%',
                background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(16px)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: '1px solid rgba(0, 163, 181, 0.3)',
                zIndex: 10,
                boxShadow: '0 0 50px rgba(0, 163, 181, 0.2)'
              }}
            >
              <ScanFace size={52} color="#00A3B5" />
            </motion.div>

            {/* Pulsing Rings to simulate scanning/matching */}
            <motion.div
              animate={{ scale: [1, 1.4, 1], opacity: [0.4, 0, 0.4] }}
              transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
              style={{ position: 'absolute', width: 160, height: 160, borderRadius: '50%', border: '2px solid rgba(0, 163, 181, 0.4)' }}
            />
            <motion.div
              animate={{ scale: [1, 2.2, 1], opacity: [0.15, 0, 0.15] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut", delay: 1 }}
              style={{ position: 'absolute', width: 220, height: 220, borderRadius: '50%', border: '1px solid rgba(255, 123, 0, 0.3)' }}
            />

            {/* Orbiting Photo Thumbnails */}
            <motion.div
              animate={{ y: [-15, 15, -15], rotate: [0, 8, -8, 0] }}
              transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
              style={{ position: 'absolute', top: 40, left: 40, width: 70, height: 90, background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(8px)', borderRadius: 12, border: '1px solid rgba(230, 57, 70, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 10px 30px rgba(230, 57, 70, 0.2)' }}
            >
              <ImageIcon size={26} color="#E63946" />
            </motion.div>

            <motion.div
              animate={{ y: [15, -15, 15], rotate: [-8, 8, -8] }}
              transition={{ duration: 6, repeat: Infinity, ease: "easeInOut", delay: 1 }}
              style={{ position: 'absolute', bottom: 50, right: 30, width: 80, height: 80, background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(8px)', borderRadius: 16, border: '1px solid rgba(255, 123, 0, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 10px 30px rgba(255, 123, 0, 0.2)' }}
            >
              <Camera size={32} color="#FF7B00" />
            </motion.div>

            <motion.div
              animate={{ y: [-10, 10, -10], rotate: [5, -5, 5] }}
              transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut", delay: 0.5 }}
              style={{ position: 'absolute', top: 120, right: 10, width: 55, height: 65, background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(8px)', borderRadius: 8, border: '1px solid rgba(133, 199, 66, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 10px 20px rgba(133, 199, 66, 0.2)' }}
            >
              <ImageIcon size={20} color="#85C742" />
            </motion.div>
          </div>
        </div>

        {/* Content */}
        <div style={{ position: 'relative', zIndex: 10, marginBottom: '1rem', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <h1 style={{ 
              fontSize: 'clamp(2rem, 4.5vw, 3.5rem)', 
              fontWeight: 800, 
              lineHeight: 1.1, 
              letterSpacing: '-0.03em',
              marginBottom: '1rem',
              color: '#fff'
            }}>
              Organize events.<br />
              <span style={{ 
                background: 'linear-gradient(90deg, #00A3B5, #FF7B00)', 
                WebkitBackgroundClip: 'text', 
                WebkitTextFillColor: 'transparent',
                display: 'inline-block'
              }}>Deliver memories.</span>
            </h1>
            <p style={{ fontSize: '1.05rem', color: 'rgba(255,255,255,0.7)', maxWidth: 460, lineHeight: 1.5 }}>
              The smartest way for event organizers to group, manage, and share thousands of photos instantly.
            </p>
          </motion.div>
        </div>
      </div>

      {/* ── Right Side: Form ── */}
      <div style={{
        flex: '1',
        maxWidth: 600,
        width: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: 'clamp(1rem, 2vw, 3rem)',
        background: '#fff',
        position: 'relative'
      }}>
        
        {/* Mobile Logo */}
        <div className="mobile-logo-container" style={{ display: 'none', marginBottom: '2rem' }}>
          <Logo />
        </div>

        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4 }}
          style={{ width: '100%', maxWidth: 420, margin: '0 auto' }}
        >
          <div style={{ marginBottom: '1.25rem' }}>
            <h2 className="font-display" style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '0.15rem', letterSpacing: '-0.02em' }}>
              Welcome back
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Sign in to your organizer dashboard
            </p>
          </div>

          {/* Error Banner */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0, y: -10 }}
                animate={{ opacity: 1, height: 'auto', y: 0 }}
                exit={{ opacity: 0, height: 0, y: -10 }}
                style={{ overflow: 'hidden' }}
              >
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '0.75rem',
                  padding: '1rem', marginBottom: '1.5rem',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.2)',
                  borderRadius: '12px',
                }}>
                  <AlertCircle size={16} color="var(--error)" style={{ flexShrink: 0 }} />
                  <span style={{ fontSize: '0.85rem', color: 'var(--error)', fontWeight: 500 }}>{error}</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Form */}
          <form onSubmit={handleSubmit} noValidate style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            
            {/* Email Field */}
            <div>
              <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '0.35rem' }}>
                Email Address
              </label>
              <div style={{ position: 'relative' }}>
                <Mail size={18} color="var(--text-muted)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)' }} />
                <input
                  className="input"
                  type="email"
                  required
                  placeholder="you@example.com"
                  value={form.email}
                  onChange={e => {
                    setForm(p => ({ ...p, email: e.target.value }));
                    if (fieldErrors.email) setFieldErrors(p => ({ ...p, email: '' }));
                  }}
                  style={{ 
                    padding: '0.875rem 1rem 0.875rem 2.75rem', 
                    fontSize: '1rem', 
                    width: '100%',
                    background: 'var(--color-surface-2)',
                    border: '1px solid transparent',
                    borderColor: fieldErrors.email ? 'var(--error)' : 'transparent',
                    borderRadius: '12px',
                    transition: 'all 0.2s'
                  }}
                  onFocus={(e) => e.target.style.background = '#fff'}
                  onBlur={(e) => { if(!e.target.value) e.target.style.background = 'var(--color-surface-2)' }}
                />
              </div>
              {fieldErrors.email && (
                <div style={{ color: 'var(--error)', fontSize: '0.8rem', marginTop: '0.5rem', fontWeight: 500 }}>{fieldErrors.email}</div>
              )}
            </div>

            {/* Password Field */}
            <div>
              <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '0.35rem' }}>
                Password
              </label>
              <div style={{ position: 'relative' }}>
                <Lock size={18} color="var(--text-muted)" style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)' }} />
                <input
                  className="input"
                  type={showPwd ? 'text' : 'password'}
                  required
                  placeholder="••••••••"
                  value={form.password}
                  onChange={e => {
                    setForm(p => ({ ...p, password: e.target.value }));
                    if (fieldErrors.password) setFieldErrors(p => ({ ...p, password: '' }));
                  }}
                  style={{ 
                    padding: '0.875rem 3rem 0.875rem 2.75rem', 
                    fontSize: '1rem', 
                    width: '100%',
                    background: 'var(--color-surface-2)',
                    border: '1px solid transparent',
                    borderColor: fieldErrors.password ? 'var(--error)' : 'transparent',
                    borderRadius: '12px',
                    transition: 'all 0.2s'
                  }}
                  onFocus={(e) => e.target.style.background = '#fff'}
                  onBlur={(e) => { if(!e.target.value) e.target.style.background = 'var(--color-surface-2)' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(v => !v)}
                  style={{
                    position: 'absolute', right: '0.5rem', top: '50%', transform: 'translateY(-50%)',
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', padding: '0.5rem', borderRadius: '8px',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                  }}
                  onMouseOver={(e) => e.currentTarget.style.background = 'var(--color-border)'}
                  onMouseOut={(e) => e.currentTarget.style.background = 'none'}
                >
                  {showPwd ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {fieldErrors.password && (
                <div style={{ color: 'var(--error)', fontSize: '0.8rem', marginTop: '0.5rem', fontWeight: 500 }}>{fieldErrors.password}</div>
              )}
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary"
              style={{
                width: '100%', justifyContent: 'center', padding: '0.875rem',
                fontSize: '1rem', marginTop: '0.5rem', fontWeight: 600,
                borderRadius: '12px', boxShadow: '0 4px 14px rgba(124, 58, 237, 0.25)'
              }}
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : 'Sign in'}
            </button>
          </form>

          {/* Footer Link */}
          <div style={{ marginTop: '1.5rem', textAlign: 'center', borderTop: '1px solid var(--border-light)', paddingTop: '1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Are you an event attendee?
            </span>
            <Link to="/scan" className="btn btn-ghost" style={{ fontSize: '0.9rem', color: 'var(--primary)', fontWeight: 600, padding: 0 }}>
              Find your photos here &rarr;
            </Link>
          </div>
        </motion.div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .login-visual-panel {
            display: none !important;
          }
          .mobile-logo-container {
            display: block !important;
            text-align: center;
          }
        }
      `}</style>
    </div>
  );
}

