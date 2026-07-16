import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ProcessingProvider } from './context/ProcessingContext';
import { ProtectedRoute } from './ProtectedRoute';
import Navbar from './components/Navbar';
import ErrorCenter from './components/ErrorCenter';

import Landing           from './pages/Landing';
import Login             from './pages/Login';

import SuperAdminPanel   from './pages/SuperAdminPanel';
import OrganizerDashboard from './pages/OrganizerDashboard';
import EventManager      from './pages/EventManager';
import AttendeeScan      from './pages/AttendeeScan';
import PhotoGallery      from './pages/PhotoGallery';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ProcessingProvider>
          <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <ErrorCenter />
            <Navbar />
            <Routes>
            {/* Public */}
            <Route path="/"        element={<Landing />} />
            <Route path="/login"   element={<Login />} />

            <Route path="/scan"    element={<AttendeeScan />} />
            <Route path="/gallery" element={<PhotoGallery />} />

            {/* Super admin only */}
            <Route path="/admin" element={
              <ProtectedRoute roles={['super_admin']}>
                <SuperAdminPanel />
              </ProtectedRoute>
            } />

            {/* Organizer + super admin */}
            <Route path="/dashboard" element={
              <ProtectedRoute roles={['organizer', 'super_admin']}>
                <OrganizerDashboard />
              </ProtectedRoute>
            } />
            <Route path="/events/:eventId" element={
              <ProtectedRoute roles={['organizer', 'super_admin']}>
                <EventManager />
              </ProtectedRoute>
            } />
            </Routes>
          </div>
        </ProcessingProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
