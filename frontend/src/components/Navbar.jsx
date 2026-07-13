import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LogOut, LayoutDashboard, Shield, Scan } from 'lucide-react';

export default function Navbar() {
  const { user, logout, isRole } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <nav className="navbar">
      {/* Logo */}
      <Link to="/" className="navbar-logo">
        <svg width="34" height="34" viewBox="0 0 34 34" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#7c3aed"/>
              <stop offset="100%" stopColor="#ec4899"/>
            </linearGradient>
          </defs>
          <rect width="34" height="34" rx="9" fill="url(#logoGrad)"/>
          {/* Camera aperture ring */}
          <circle cx="17" cy="17" r="9" stroke="white" strokeWidth="1.5" fill="none" strokeDasharray="3 1.5"/>
          {/* Face outline */}
          <circle cx="17" cy="15" r="4" stroke="white" strokeWidth="1.5" fill="none"/>
          <path d="M10.5 24.5 C10.5 21 13.5 19 17 19 C20.5 19 23.5 21 23.5 24.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
        </svg>
        <span style={{ background: 'linear-gradient(135deg,#7c3aed,#ec4899)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
          Urface
        </span>
      </Link>

      {/* Nav actions */}
      <div className="navbar-actions">
        {!user && location.pathname !== '/scan' && (
          <Link to="/scan" className="btn btn-ghost btn-sm">
            <Scan size={14} /> Find My Photos
          </Link>
        )}

        {user ? (
          <>
            {isRole('super_admin') && (
              <Link to="/admin" className="btn btn-ghost btn-sm">
                <Shield size={14} /> Admin
              </Link>
            )}
            {(isRole('organizer') || isRole('super_admin')) && (
              <Link to="/dashboard" className="btn btn-ghost btn-sm">
                <LayoutDashboard size={14} /> Dashboard
              </Link>
            )}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)',
              padding: '0.375rem 0.75rem', border: '1px solid var(--color-border)',
            }}>
              <div style={{
                width: 26, height: 26, borderRadius: '50%',
                background: 'linear-gradient(135deg,#7c3aed,#ec4899)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '0.7rem', fontWeight: 700, color: '#fff',
              }}>
                {user.role === 'super_admin' ? '⚡' : user.role === 'organizer' ? '📸' : '👤'}
              </div>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                {user.role === 'super_admin' ? 'Super Admin' : user.role === 'organizer' ? 'Organizer' : 'Attendee'}
              </span>
            </div>
            <button onClick={handleLogout} className="btn btn-ghost btn-sm">
              <LogOut size={14} /> Logout
            </button>
          </>
        ) : (
          <Link to="/login" className="btn btn-primary btn-sm">
            Organizer Sign In
          </Link>
        )}
      </div>
    </nav>
  );
}
