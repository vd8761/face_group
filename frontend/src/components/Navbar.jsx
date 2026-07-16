import { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LayoutDashboard, LogOut, Scan, Shield, UserCircle, Camera, ChevronDown } from 'lucide-react';
import Logo from './Logo';

export default function Navbar() {
  const { user, logout, isRole } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 72);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const handleLogout = () => { logout(); navigate('/'); };
  const isPublicPage = ['/', '/login', '/scan'].includes(location.pathname);

  const roleLabel = user?.role === 'super_admin' ? 'Super Admin'
    : user?.role === 'organizer' ? 'Organizer' : 'Attendee';

  const roleColor = user?.role === 'super_admin' ? '#EF4444'
    : user?.role === 'organizer' ? '#06B6D4' : '#10B981';

  return (
    <nav className="navbar" style={{ boxShadow: scrolled ? 'var(--shadow-md)' : 'none' }}>
      {/* ── Logo ── */}
      <Link to="/" className="navbar-logo">
        <Logo size="sm" />
      </Link>

      {/* ── Nav Links Removed ── */}

      {/* ── Actions ── */}
      <div className="navbar-actions">
        {/* Find My Photos */}
        {!user && location.pathname !== '/scan' && (
          <Link to="/scan">
            <button
              className="btn btn-ghost btn-sm"
              style={{ color: 'var(--teal-dark)', fontWeight: 600 }}
            >
              <Scan size={14} className="hide-on-mobile" />
              <span className="hide-on-mobile">Find My Photos</span>
              <span style={{ display: 'none' }} className="mobile-only-inline">Find Photos</span>
            </button>
          </Link>
        )}

        {user ? (
          <>
            {/* Admin */}
            {isRole('super_admin') && (
              <Link to="/admin">
                <button className="btn btn-ghost btn-sm">
                  <Shield size={14} style={{ color: '#EF4444' }} />
                  Admin
                </button>
              </Link>
            )}

            {/* Dashboard */}
            {(isRole('organizer') || isRole('super_admin')) && (
              <Link to="/dashboard">
                <button className="btn btn-ghost btn-sm">
                  <LayoutDashboard size={14} />
                  Dashboard
                </button>
              </Link>
            )}

            {/* User Pill */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              background: 'var(--base)',
              border: '1.5px solid var(--border)',
              borderRadius: 'var(--r-full)',
              padding: '0.3rem 0.875rem 0.3rem 0.375rem',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: `linear-gradient(135deg, ${roleColor}30, ${roleColor}15)`,
                border: `2px solid ${roleColor}40`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {user?.role === 'super_admin'
                  ? <Shield size={13} color={roleColor} />
                  : user?.role === 'organizer'
                    ? <Camera size={13} color={roleColor} />
                    : <UserCircle size={13} color={roleColor} />
                }
              </div>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--navy)' }}>
                {roleLabel}
              </span>
            </div>

            {/* Logout */}
            <button onClick={handleLogout} className="btn btn-ghost btn-sm">
              <LogOut size={14} />
              Logout
            </button>
          </>
        ) : (
          /* Primary CTA */
          location.pathname !== '/login' && (
            <Link to="/login">
              <button
                className="btn btn-sm"
                style={{
                  background: scrolled && isPublicPage ? 'var(--teal)' : 'transparent',
                  color: scrolled && isPublicPage ? '#fff' : 'var(--navy)',
                  border: scrolled && isPublicPage ? '1.5px solid var(--teal)' : '1.5px solid var(--border)',
                  borderRadius: 'var(--r-md)',
                  fontWeight: 700,
                  transition: 'all 0.25s ease',
                  boxShadow: scrolled && isPublicPage ? 'var(--shadow-glow)' : 'none',
                }}
              >
                <span className="hide-on-mobile">Organizer Sign In</span>
                <span style={{ display: 'none' }} className="mobile-only-inline">Sign In</span>
              </button>
            </Link>
          )
        )}
      </div>
    </nav>
  );
}
