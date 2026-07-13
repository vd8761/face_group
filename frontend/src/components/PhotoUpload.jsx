import { useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, CloudUpload, X, CheckCircle2, AlertCircle,
  Loader2, Image, RefreshCw, RotateCcw, FileWarning
} from 'lucide-react';
import api from '../api/client';

const BATCH_SIZE = 5;

export default function PhotoUpload({ eventId, onUploadComplete }) {
  const [dragOver, setDragOver]     = useState(false);
  const [files, setFiles]           = useState([]);       // pending queue
  const [uploading, setUploading]   = useState(false);
  const [failedFiles, setFailedFiles] = useState([]);     // files that failed
  const [uploadedCount, setUploadedCount] = useState(0);
  const [progress, setProgress]     = useState({ batchDone: 0, batchTotal: 0 });
  const [done, setDone]             = useState(false);
  const inputRef = useRef(null);

  /* ── file selection ── */
  const addFiles = useCallback((newFiles) => {
    const validTypes = ['image/jpeg', 'image/png', 'image/heic', 'image/webp'];
    const filtered = Array.from(newFiles).filter(f => validTypes.includes(f.type));
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size));
      return [...prev, ...filtered.filter(f => !existing.has(f.name + f.size))];
    });
    setDone(false);
    setFailedFiles([]);
  }, []);

  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));
  const removeFailedFile = (idx) => setFailedFiles(prev => prev.filter((_, i) => i !== idx));

  /* ── core upload logic — works for both first-run and retry ── */
  const runUpload = async (filesToUpload) => {
    setUploading(true);
    setDone(false);

    const batches = [];
    for (let i = 0; i < filesToUpload.length; i += BATCH_SIZE) {
      batches.push(filesToUpload.slice(i, i + BATCH_SIZE));
    }

    let accepted    = 0;
    let newFailed   = [];
    let batchesDone = 0;

    setProgress({ batchDone: 0, batchTotal: batches.length });

    for (const batch of batches) {
      try {
        const formData = new FormData();
        batch.forEach(f => formData.append('files', f));

        const { data } = await api.post(
          `/api/photos/events/${eventId}/upload`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 }
        );

        accepted += data.accepted || 0;
        // If the server skipped some (wrong type / too large) they count as failed
        if ((data.skipped || 0) > 0) {
          // We can't tell which individual ones were skipped without more detail
          // so we add all of them to the retry queue conservatively only if accepted == 0
          if ((data.accepted || 0) === 0) {
            newFailed = [...newFailed, ...batch];
          }
        }
      } catch {
        // Entire batch failed — add all files to retry queue
        newFailed = [...newFailed, ...batch];
      }

      batchesDone++;
      setProgress({ batchDone: batchesDone, batchTotal: batches.length });
    }

    setUploadedCount(prev => prev + accepted);
    setFailedFiles(newFailed);
    setFiles([]);
    setUploading(false);
    setDone(true);

    if (accepted > 0) onUploadComplete?.({ accepted });
  };

  const handleUpload = () => { if (files.length && !uploading) runUpload(files); };
  const handleRetry  = () => { if (failedFiles.length && !uploading) runUpload(failedFiles); };

  const reset = () => {
    setFiles([]); setFailedFiles([]); setDone(false);
    setUploadedCount(0); setProgress({ batchDone: 0, batchTotal: 0 });
  };

  const pct = progress.batchTotal > 0
    ? Math.round((progress.batchDone / progress.batchTotal) * 100)
    : 0;

  const totalSizeMB = files.reduce((s, f) => s + f.size, 0) / 1024 / 1024;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* ── Drop zone — only show when not uploading and no result yet ── */}
      {!done && (
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
          onDrop={(e) => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files); }}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef} type="file" multiple
            accept="image/jpeg,image/png,image/heic,image/webp"
            style={{ display: 'none' }}
            onChange={(e) => addFiles(e.target.files)}
          />
          <motion.div animate={{ y: dragOver ? -6 : 0 }} transition={{ type: 'spring', stiffness: 300 }}>
            <div style={{
              width: 60, height: 60,
              background: dragOver ? 'var(--accent)' : 'var(--accent-soft)',
              borderRadius: '16px', display: 'flex', alignItems: 'center',
              justifyContent: 'center', margin: '0 auto 1rem', transition: 'all 0.2s',
            }}>
              <CloudUpload size={26} color={dragOver ? '#fff' : 'var(--accent-light)'} />
            </div>
            <p style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.375rem' }}>
              Drop photos here or <span style={{ color: 'var(--accent-light)' }}>browse</span>
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              JPEG · PNG · HEIC · WEBP &nbsp;·&nbsp; Max 25 MB each &nbsp;·&nbsp; Batches of {BATCH_SIZE}
            </p>
          </motion.div>
        </div>
      )}

      {/* ── Pending file list ── */}
      <AnimatePresence>
        {files.length > 0 && !uploading && !done && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            style={{ background: '#fff', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}
          >
            {/* header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '0.875rem 1.125rem', borderBottom: '1px solid var(--color-border)',
              background: 'var(--color-surface-2)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Image size={14} color="var(--accent-light)" />
                <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                  {files.length} photo{files.length !== 1 ? 's' : ''} selected
                </span>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  ({totalSizeMB.toFixed(1)} MB)
                </span>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setFiles([])}>
                <RefreshCw size={12} /> Clear all
              </button>
            </div>
            {/* rows */}
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {files.slice(0, 12).map((f, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: '0.75rem',
                  padding: '0.625rem 1.125rem',
                  borderBottom: i < Math.min(files.length, 12) - 1 ? '1px solid var(--color-border)' : 'none',
                }}>
                  <div style={{ width: 32, height: 32, borderRadius: '8px', background: 'var(--color-surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <Image size={14} color="var(--text-muted)" />
                  </div>
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div style={{ fontSize: '0.8375rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{(f.size / 1024 / 1024).toFixed(1)} MB</div>
                  </div>
                  <button className="btn btn-ghost btn-icon btn-sm" onClick={() => removeFile(i)}><X size={13} /></button>
                </div>
              ))}
              {files.length > 12 && (
                <div style={{ padding: '0.625rem', fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                  …and {files.length - 12} more files
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Upload progress bar ── */}
      <AnimatePresence>
        {uploading && (
          <motion.div
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            style={{
              background: 'var(--accent-soft)', border: '1px solid rgba(124,58,237,0.2)',
              borderRadius: 'var(--radius-md)', padding: '1rem 1.25rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.625rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Loader2 size={14} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
                <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--accent-light)' }}>
                  Uploading batch {progress.batchDone + 1} of {progress.batchTotal}…
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
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
              You can switch tabs — upload will continue in the background
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Result summary ── */}
      <AnimatePresence>
        {done && !uploading && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>

            {/* Success banner */}
            {uploadedCount > 0 && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.75rem',
                padding: '0.875rem 1.125rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(22,163,74,0.07)', border: '1px solid rgba(22,163,74,0.2)',
                marginBottom: failedFiles.length > 0 ? '0.875rem' : 0,
              }}>
                <CheckCircle2 size={18} color="var(--success)" style={{ flexShrink: 0 }} />
                <div>
                  <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--success)' }}>
                    {uploadedCount} photo{uploadedCount !== 1 ? 's' : ''} uploaded successfully
                  </p>
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Face processing is running in the background
                  </p>
                </div>
              </div>
            )}

            {/* Failed files panel */}
            {failedFiles.length > 0 && (
              <div style={{
                background: '#fff', border: '1px solid rgba(239,68,68,0.25)',
                borderRadius: 'var(--radius-lg)', overflow: 'hidden',
              }}>
                {/* Failed header */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '0.875rem 1.125rem',
                  background: 'rgba(239,68,68,0.05)',
                  borderBottom: '1px solid rgba(239,68,68,0.15)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <FileWarning size={16} color="var(--error)" />
                    <span style={{ fontWeight: 700, fontSize: '0.875rem', color: 'var(--error)' }}>
                      {failedFiles.length} photo{failedFiles.length !== 1 ? 's' : ''} failed to upload
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <button
                      className="btn btn-sm"
                      onClick={handleRetry}
                      style={{
                        background: 'var(--error)', color: '#fff', border: 'none',
                        display: 'flex', alignItems: 'center', gap: '0.375rem',
                      }}
                    >
                      <RotateCcw size={13} /> Retry All Failed
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setFailedFiles([])}>
                      <X size={12} /> Dismiss
                    </button>
                  </div>
                </div>

                {/* Failed file rows */}
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  {failedFiles.map((f, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.04 }}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '0.75rem',
                        padding: '0.625rem 1.125rem',
                        borderBottom: i < failedFiles.length - 1 ? '1px solid rgba(239,68,68,0.1)' : 'none',
                        background: i % 2 === 0 ? 'transparent' : 'rgba(239,68,68,0.02)',
                      }}
                    >
                      {/* File icon */}
                      <div style={{
                        width: 34, height: 34, borderRadius: '8px',
                        background: 'rgba(239,68,68,0.1)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      }}>
                        <AlertCircle size={15} color="var(--error)" />
                      </div>

                      {/* Name + size */}
                      <div style={{ flex: 1, overflow: 'hidden' }}>
                        <div style={{
                          fontSize: '0.8375rem', fontWeight: 500,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          color: 'var(--text-primary)',
                        }}>
                          {f.name}
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--error)', opacity: 0.8, marginTop: '1px' }}>
                          {(f.size / 1024 / 1024).toFixed(1)} MB · Upload failed
                        </div>
                      </div>

                      {/* Per-file retry */}
                      <button
                        className="btn btn-sm"
                        onClick={() => runUpload([f])}
                        style={{
                          background: 'rgba(239,68,68,0.08)', color: 'var(--error)',
                          border: '1px solid rgba(239,68,68,0.2)',
                          display: 'flex', alignItems: 'center', gap: '0.35rem',
                          flexShrink: 0,
                        }}
                      >
                        <RotateCcw size={12} /> Retry
                      </button>

                      {/* Remove from failed list */}
                      <button
                        className="btn btn-ghost btn-icon btn-sm"
                        onClick={() => removeFailedFile(i)}
                        style={{ flexShrink: 0 }}
                      >
                        <X size={12} />
                      </button>
                    </motion.div>
                  ))}
                </div>

                {/* Retry all footer */}
                {failedFiles.length > 1 && (
                  <div style={{
                    padding: '0.75rem 1.125rem',
                    borderTop: '1px solid rgba(239,68,68,0.15)',
                    background: 'rgba(239,68,68,0.03)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  }}>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      Tip: Check your internet connection before retrying
                    </span>
                    <button
                      className="btn btn-sm"
                      onClick={handleRetry}
                      disabled={uploading}
                      style={{ background: 'var(--error)', color: '#fff', border: 'none', display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                    >
                      <RotateCcw size={13} /> Retry {failedFiles.length} Failed
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Upload more / reset */}
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
              <button className="btn btn-ghost btn-sm" onClick={reset}>
                <CloudUpload size={14} /> Upload More Photos
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Upload button ── */}
      {!done && (
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn btn-primary"
            disabled={!files.length || uploading}
            onClick={handleUpload}
          >
            {uploading
              ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Uploading…</>
              : <><Upload size={16} /> Upload {files.length > 0 ? `${files.length} Photo${files.length !== 1 ? 's' : ''}` : 'Photos'}</>}
          </button>
          {files.length > 0 && !uploading && (
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              {Math.ceil(files.length / BATCH_SIZE)} batch{Math.ceil(files.length / BATCH_SIZE) !== 1 ? 'es' : ''} of {BATCH_SIZE}
            </span>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
