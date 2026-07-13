import { useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, CloudUpload, X, CheckCircle2, AlertCircle, Loader2, Image, RefreshCw } from 'lucide-react';
import api from '../api/client';

const BATCH_SIZE = 5; // Upload 5 photos at a time to avoid timeout

export default function PhotoUpload({ eventId, onUploadComplete }) {
  const [dragOver, setDragOver]   = useState(false);
  const [files, setFiles]         = useState([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress]  = useState({ done: 0, total: 0, failed: 0 });
  const [result, setResult]      = useState(null);
  const inputRef = useRef(null);

  const addFiles = useCallback((newFiles) => {
    const validTypes = ['image/jpeg', 'image/png', 'image/heic', 'image/webp'];
    const filtered = Array.from(newFiles).filter(f => validTypes.includes(f.type));
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size));
      return [...prev, ...filtered.filter(f => !existing.has(f.name + f.size))];
    });
    setResult(null);
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

    // Split into batches of BATCH_SIZE
    const batches = [];
    for (let i = 0; i < files.length; i += BATCH_SIZE) {
      batches.push(files.slice(i, i + BATCH_SIZE));
    }

    let totalAccepted = 0;
    let totalSkipped  = 0;
    let totalFailed   = 0;
    let batchesDone   = 0;

    setProgress({ done: 0, total: batches.length, failed: 0 });

    for (const batch of batches) {
      try {
        const formData = new FormData();
        batch.forEach(f => formData.append('files', f));

        const { data } = await api.post(
          `/api/photos/events/${eventId}/upload`,
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 120000, // 2 min per batch
          }
        );

        totalAccepted += data.accepted || 0;
        totalSkipped  += data.skipped  || 0;
        batchesDone++;
        setProgress({ done: batchesDone, total: batches.length, failed: totalFailed });
      } catch (err) {
        totalFailed++;
        batchesDone++;
        setProgress(p => ({ ...p, done: batchesDone, failed: totalFailed }));
        console.error('Batch upload error:', err);
      }
    }

    setUploading(false);

    if (totalAccepted > 0) {
      setResult({ success: true, accepted: totalAccepted, skipped: totalSkipped, failed: totalFailed });
      setFiles([]);
      onUploadComplete?.({ accepted: totalAccepted });
    } else {
      setResult({ success: false, error: `All batches failed. Check your connection and try again.` });
    }
  };

  const pct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const totalSizeMB = files.reduce((s, f) => s + f.size, 0) / 1024 / 1024;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Drop zone */}
      <div
        style={{
          border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--color-border)'}`,
          borderRadius: 'var(--radius-xl)',
          background: dragOver ? 'rgba(124,58,237,0.04)' : 'var(--color-surface-2)',
          padding: '3rem 2rem',
          cursor: 'pointer',
          transition: 'all 0.2s',
          textAlign: 'center',
        }}
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
        <motion.div animate={{ y: dragOver ? -6 : 0 }} transition={{ type: 'spring', stiffness: 300 }}>
          <div style={{
            width: 60, height: 60, background: dragOver ? 'var(--accent)' : 'var(--accent-soft)',
            borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 1rem', transition: 'all 0.2s',
          }}>
            <CloudUpload size={26} color={dragOver ? '#fff' : 'var(--accent-light)'} />
          </div>
          <p style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.375rem' }}>
            Drop photos here or <span style={{ color: 'var(--accent-light)' }}>browse</span>
          </p>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            JPEG, PNG, HEIC, WEBP · Max 25 MB each · Uploads in batches of {BATCH_SIZE}
          </p>
        </motion.div>
      </div>

      {/* File list */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            style={{
              background: '#fff',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              overflow: 'hidden',
            }}
          >
            {/* File list header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '0.875rem 1.125rem',
              borderBottom: '1px solid var(--color-border)',
              background: 'var(--color-surface-2)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Image size={14} color="var(--accent-light)" />
                <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                  {files.length} photo{files.length !== 1 ? 's' : ''} selected
                </span>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  ({totalSizeMB.toFixed(1)} MB total)
                </span>
              </div>
              <button
                className="btn btn-ghost btn-sm"
                onClick={(e) => { e.stopPropagation(); setFiles([]); }}
              >
                <RefreshCw size={12} /> Clear all
              </button>
            </div>

            {/* File rows */}
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {files.slice(0, 12).map((f, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '0.75rem',
                    padding: '0.625rem 1.125rem',
                    borderBottom: i < Math.min(files.length, 12) - 1 ? '1px solid var(--color-border)' : 'none',
                  }}
                >
                  <div style={{
                    width: 34, height: 34, borderRadius: '8px',
                    background: 'var(--color-surface-2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  }}>
                    <Image size={15} color="var(--text-muted)" />
                  </div>
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div style={{
                      fontSize: '0.8375rem', fontWeight: 500,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      color: 'var(--text-primary)',
                    }}>
                      {f.name}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '1px' }}>
                      {(f.size / 1024 / 1024).toFixed(1)} MB
                    </div>
                  </div>
                  <button
                    className="btn btn-ghost btn-icon btn-sm"
                    onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                    style={{ flexShrink: 0 }}
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
              {files.length > 12 && (
                <div style={{ padding: '0.625rem 1.125rem', fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                  …and {files.length - 12} more files
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload progress */}
      <AnimatePresence>
        {uploading && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            style={{
              background: 'var(--accent-soft)',
              border: '1px solid rgba(124,58,237,0.2)',
              borderRadius: 'var(--radius-md)',
              padding: '1rem 1.25rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.625rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Loader2 size={14} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
                <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--accent-light)' }}>
                  Uploading batch {progress.done + 1} of {progress.total}…
                </span>
              </div>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-light)' }}>{pct}%</span>
            </div>
            <div style={{ height: 6, background: 'rgba(124,58,237,0.15)', borderRadius: 999, overflow: 'hidden' }}>
              <motion.div
                style={{ height: '100%', background: 'linear-gradient(90deg,#7c3aed,#ec4899)', borderRadius: 999 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
            {progress.failed > 0 && (
              <p style={{ fontSize: '0.75rem', color: 'var(--warning)', marginTop: '0.5rem' }}>
                ⚠ {progress.failed} batch(es) failed — others are still uploading
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Result feedback */}
      <AnimatePresence>
        {result && !uploading && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: '0.75rem',
              padding: '1rem 1.125rem', borderRadius: 'var(--radius-md)',
              background: result.success ? 'rgba(22,163,74,0.07)' : 'rgba(239,68,68,0.08)',
              border: `1px solid ${result.success ? 'rgba(22,163,74,0.2)' : 'rgba(239,68,68,0.25)'}`,
            }}
          >
            {result.success
              ? <CheckCircle2 size={18} color="var(--success)" style={{ flexShrink: 0, marginTop: 1 }} />
              : <AlertCircle size={18} color="var(--error)" style={{ flexShrink: 0, marginTop: 1 }} />}
            <div>
              {result.success ? (
                <>
                  <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--success)', marginBottom: '0.125rem' }}>
                    {result.accepted} photo{result.accepted !== 1 ? 's' : ''} uploaded successfully!
                  </p>
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Face processing is running in the background.
                    {result.failed > 0 && ` ${result.failed} batch(es) had errors.`}
                    {result.skipped > 0 && ` ${result.skipped} file(s) skipped (wrong format or too large).`}
                  </p>
                </>
              ) : (
                <p style={{ fontSize: '0.875rem', color: 'var(--error)' }}>{result.error}</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload button */}
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
        <button
          className="btn btn-primary"
          disabled={!files.length || uploading}
          onClick={handleUpload}
          style={{ gap: '0.5rem' }}
        >
          {uploading
            ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Uploading…</>
            : <><Upload size={16} /> Upload {files.length > 0 ? `${files.length} Photo${files.length !== 1 ? 's' : ''}` : 'Photos'}</>}
        </button>
        {files.length > 0 && !uploading && (
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Will upload in {Math.ceil(files.length / BATCH_SIZE)} batch{Math.ceil(files.length / BATCH_SIZE) !== 1 ? 'es' : ''} of {BATCH_SIZE}
          </span>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
