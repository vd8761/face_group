import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Camera, LayoutDashboard, LogOut, Scan, Shield, UserCircle } from 'lucide-react';
import Logo from './Logo';

export default function Navbar() {
  const { user, logout, isRole } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  const roleIcon = user?.role === 'super_admin'
    ? <Shield size={14} />
    : user?.role === 'organizer'
      ? <Camera size={14} />
      : <UserCircle size={14} />;

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-logo">
        <Logo />
      </Link>

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
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              background: 'var(--color-surface-2)',
              borderRadius: 'var(--radius-pill)',
              padding: '0.375rem 0.75rem',
              border: '1px solid var(--color-border)',
            }}>
              <div style={{
                width: 26,
                height: 26,
                borderRadius: '50%',
                background: 'linear-gradient(135deg,var(--primary),var(--accent2))',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
              }}>
                {roleIcon}
              </div>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
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
