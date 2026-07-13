import { useRef, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Upload, CloudUpload, X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import api from '../api/client';

export default function PhotoUpload({ eventId, onUploadComplete }) {
  const [dragOver, setDragOver] = useState(false);
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  const addFiles = useCallback((newFiles) => {
    const validTypes = ['image/jpeg', 'image/png', 'image/heic', 'image/webp'];
    const filtered = Array.from(newFiles).filter(f => validTypes.includes(f.type));
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size));
      return [...prev, ...filtered.filter(f => !existing.has(f.name + f.size))];
    });
  }, []);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));

  const handleUpload = async () => {
    if (!files.length || uploading) return;
    setUploading(true);
    setResult(null);

    const formData = new FormData();
    files.forEach(f => formData.append('files', f));

    try {
      const { data } = await api.post(`/api/photos/events/${eventId}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult({ success: true, data });
      setFiles([]);
      onUploadComplete?.(data);
    } catch (err) {
      setResult({ success: false, error: err.response?.data?.detail || 'Upload failed' });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Drop zone */}
      <div
        className={`upload-zone ${dragOver ? 'drag-over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/heic,image/webp"
          style={{ display: 'none' }}
          onChange={(e) => addFiles(e.target.files)}
        />
        <motion.div
          animate={{ y: dragOver ? -6 : 0 }}
          transition={{ type: 'spring', stiffness: 300 }}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.75rem' }}
        >
          <div style={{
            width: 56, height: 56,
            background: 'var(--accent-soft)',
            borderRadius: '14px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <CloudUpload size={26} color="var(--accent-light)" />
          </div>
          <div>
            <p style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '0.25rem' }}>
              Drop photos here or <span style={{ color: 'var(--accent-light)' }}>browse</span>
            </p>
            <p className="text-sm text-muted">JPEG, PNG, HEIC, WEBP · Max 25 MB each</p>
          </div>
        </motion.div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div style={{
          background: 'var(--color-surface-2)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          padding: '0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          maxHeight: 200,
          overflowY: 'auto',
        }}>
          <div className="flex justify-between items-center mb-1">
            <span className="text-sm font-semibold">{files.length} files selected</span>
            <button className="btn btn-ghost btn-sm" onClick={() => setFiles([])}>Clear all</button>
          </div>
          {files.slice(0, 10).map((f, i) => (
            <div key={i} className="flex items-center justify-between gap-2" style={{ padding: '0.375rem 0' }}>
              <div className="flex items-center gap-2">
                <Upload size={13} color="var(--text-muted)" />
                <span className="text-sm" style={{ color: 'var(--text-secondary)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.name}
                </span>
                <span className="text-xs text-muted">({(f.size / 1024 / 1024).toFixed(1)} MB)</span>
              </div>
              <button className="btn-icon btn-ghost btn" onClick={(e) => { e.stopPropagation(); removeFile(i); }}>
                <X size={12} />
              </button>
            </div>
          ))}
          {files.length > 10 && <p className="text-xs text-muted text-center">…and {files.length - 10} more</p>}
        </div>
      )}

      {/* Result feedback */}
      {result && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            padding: '0.875rem 1rem',
            borderRadius: 'var(--radius-md)',
            background: result.success ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
            border: `1px solid ${result.success ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
          }}
        >
          {result.success
            ? <CheckCircle2 size={18} color="var(--success)" />
            : <AlertCircle size={18} color="var(--error)" />}
          <span className="text-sm" style={{ color: result.success ? 'var(--success)' : 'var(--error)' }}>
            {result.success
              ? `✅ ${result.data.accepted} photos uploaded — processing in background`
              : `❌ ${result.error}`}
          </span>
        </motion.div>
      )}

      {/* Upload button */}
      <button
        className="btn btn-primary"
        disabled={!files.length || uploading}
        onClick={handleUpload}
        style={{ alignSelf: 'flex-start' }}
      >
        {uploading
          ? <><Loader2 size={16} className="spin" /> Uploading…</>
          : <><Upload size={16} /> Upload {files.length > 0 ? `${files.length} photos` : 'Photos'}</>}
      </button>

      <style>{`.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
