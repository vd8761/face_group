import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Download, CheckSquare, Square, Trash2, Images, AlertTriangle,
  Loader2, X, Camera
} from 'lucide-react';
import api from '../api/client';
import GalleryGrid from '../components/GalleryGrid';

export default function PhotoGallery() {
  const location = useLocation();
  const navigate = useNavigate();
  const scanResult = location.state?.scanResult;
  const eventId    = location.state?.eventId;

  const [photos, setPhotos]     = useState(scanResult?.photos || []);
  const [selected, setSelected] = useState(new Set());
  const [downloading, setDownloading] = useState(false);
  const [deletingScan, setDeletingScan] = useState(false);
  const [deleted, setDeleted]   = useState(false);

  useEffect(() => {
    if (!scanResult) { navigate('/scan'); }
  }, [scanResult, navigate]);

  if (!scanResult) return null;

  const togglePhoto = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll  = () => setSelected(new Set(photos.map(p => p.id)));
  const clearSel   = () => setSelected(new Set());

  const downloadZip = async (ids) => {
    setDownloading(true);
    try {
      const response = await api.post('/api/downloads/zip',
        { photo_ids: ids },
        { responseType: 'blob' }
      );
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'my_photos.zip';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert('Download failed. Please try again.');
    } finally { setDownloading(false); }
  };

  const downloadSingle = async (photo) => {
    try {
      const { data } = await api.get(`/api/photos/${photo.id}/download`);
      window.open(data.url, '_blank');
    } catch (e) { alert('Download failed.'); }
  };

  const deleteSelfie = async () => {
    if (!confirm('Delete your face data? You will need to scan again to retrieve photos.')) return;
    setDeletingScan(true);
    try {
      await api.delete(`/api/faces/scans/${scanResult.scan_id}`);
      setDeleted(true);
    } catch (e) { alert('Deletion failed.'); }
    finally { setDeletingScan(false); }
  };

  const selectedList = Array.from(selected);

  return (
    <div className="page">
      <div className="container">
        {/* Header */}
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="flex items-center justify-between mb-6" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 style={{ marginBottom: '0.25rem' }}>
              {scanResult.matched
                ? <>Your Photos <span className="gradient-text">({photos.length})</span></>
                : 'No Match Found'}
            </h2>
            <p className="text-secondary text-sm">
              {scanResult.matched
                ? `Match confidence: ${(scanResult.match_confidence * 100).toFixed(0)}%`
                : 'We couldn\'t find you in this event\'s photos. Try a clearer, front-facing photo.'}
            </p>
          </div>

          <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
            {/* Erase data (GDPR) */}
            {!deleted && scanResult.scan_id && (
              <button className="btn btn-danger btn-sm" onClick={deleteSelfie} disabled={deletingScan}>
                {deletingScan ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash2 size={13} />}
                Erase My Data
              </button>
            )}
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/scan')}>
              <Camera size={13} /> Scan Again
            </button>
          </div>
        </motion.div>

        {/* Deletion confirmation */}
        <AnimatePresence>
          {deleted && (
            <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              style={{ background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 'var(--radius-md)', padding: '0.875rem 1rem', marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
              <span style={{ color: 'var(--success)', fontSize: '0.875rem' }}>✅ Your face data has been erased. This gallery will clear on next refresh.</span>
            </motion.div>
          )}
        </AnimatePresence>

        {!scanResult.matched ? (
          <div className="card text-center" style={{ padding: '4rem 2rem', maxWidth: 480, margin: '0 auto' }}>
            <AlertTriangle size={48} color="var(--warning)" style={{ margin: '0 auto 1rem' }} />
            <h3 style={{ marginBottom: '0.75rem' }}>No photos found</h3>
            <p className="text-secondary text-sm" style={{ marginBottom: '1.5rem' }}>
              Make sure you're using a clear, front-facing photo with good lighting.
              The event organizer may still be processing photos.
            </p>
            <button className="btn btn-primary" onClick={() => navigate('/scan')}>
              <Camera size={16} /> Try Again
            </button>
          </div>
        ) : (
          <>
            {/* Selection controls */}
            <div className="flex items-center gap-3 mb-4" style={{ flexWrap: 'wrap' }}>
              <button className="btn btn-ghost btn-sm" onClick={selected.size === photos.length ? clearSel : selectAll}>
                {selected.size === photos.length
                  ? <><Square size={14} /> Deselect All</>
                  : <><CheckSquare size={14} /> Select All</>}
              </button>
              {selected.size > 0 && (
                <span className="text-sm text-muted">{selected.size} selected</span>
              )}
              <button
                className="btn btn-primary btn-sm"
                style={{ marginLeft: 'auto' }}
                onClick={() => downloadZip(photos.map(p => p.id))}
                disabled={downloading}
              >
                {downloading
                  ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Preparing…</>
                  : <><Download size={13} /> Download All ({photos.length})</>}
              </button>
            </div>

            {/* Gallery */}
            <GalleryGrid photos={photos} selected={selected} onToggle={togglePhoto} />

            {/* Floating action bar (when selection active) */}
            <AnimatePresence>
              {selected.size > 0 && (
                <motion.div
                  className="fab-bar"
                  initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 24 }}
                >
                  <span className="text-sm font-semibold">{selected.size} selected</span>
                  <div style={{ width: 1, height: 20, background: 'var(--color-border)' }} />
                  <button className="btn btn-primary btn-sm" onClick={() => downloadZip(selectedList)} disabled={downloading}>
                    {downloading
                      ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Preparing…</>
                      : <><Download size={13} /> Download ZIP</>}
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={clearSel}><X size={13} /></button>
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
