import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Camera, LogOut, LayoutDashboard, Shield, Menu, X } from 'lucide-react';
import { useState } from 'react';

export default function Navbar() {
  const { user, logout, isRole } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-logo">
        <div className="navbar-logo-icon">
          <Camera size={18} color="#fff" strokeWidth={2.5} />
        </div>
        PhotoGroup
      </Link>

      <div className="navbar-actions" style={{ gap: '0.5rem' }}>
        {user ? (
          <>
            {isRole('super_admin') && (
              <Link to="/admin" className="btn btn-ghost btn-sm">
                <Shield size={15} /> Admin
              </Link>
            )}
            {isRole('organizer') && (
              <Link to="/dashboard" className="btn btn-ghost btn-sm">
                <LayoutDashboard size={15} /> Dashboard
              </Link>
            )}
            <span className="text-xs text-muted" style={{ fontWeight: 500, padding: '0 0.25rem' }}>
              {user.role === 'super_admin' ? '⚡ Super Admin' :
               user.role === 'organizer'   ? '📸 Organizer'  : '👤 Attendee'}
            </span>
            <button onClick={handleLogout} className="btn btn-ghost btn-sm">
              <LogOut size={15} /> Logout
            </button>
          </>
        ) : (
          <Link to="/login" className="btn btn-secondary btn-sm">
            Sign In
          </Link>
        )}
      </div>
    </nav>
  );
}
