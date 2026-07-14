import { useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, CloudUpload, X, CheckCircle2, AlertCircle,
  Loader2, Image, RefreshCw, RotateCcw, FileWarning,
  FolderOpen, Link, HardDriveDownload
} from 'lucide-react';
import api from '../api/client';

const BATCH_SIZE = 5;

export default function PhotoUpload({ eventId, onUploadComplete }) {
  const [uploadMode, setUploadMode]   = useState('local');   // 'local' | 'drive'
  const [dragOver, setDragOver]       = useState(false);
  const [files, setFiles]             = useState([]);
  const [uploading, setUploading]     = useState(false);
  const [failedFiles, setFailedFiles]       = useState([]);
  const [duplicateNames, setDuplicateNames] = useState([]);
  const [uploadedCount, setUploadedCount]   = useState(0);
  const [progress, setProgress]       = useState({ batchDone: 0, batchTotal: 0 });
  const [done, setDone]               = useState(false);

  // Google Drive state
  const [driveUrl, setDriveUrl]           = useState('');
  const [driveImporting, setDriveImporting] = useState(false);
  const [driveResult, setDriveResult]     = useState(null);  // { queued, message, files }
  const [driveError, setDriveError]       = useState('');

  const inputRef = useRef(null);

  /* ── file selection ── */
  const addFiles = useCallback((newFiles) => {
    const validTypes = ['image/jpeg', 'image/jpg'];
    const filtered = Array.from(newFiles).filter(f => validTypes.includes(f.type) || f.name.toLowerCase().endsWith('.jpg') || f.name.toLowerCase().endsWith('.jpeg'));
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size));
      return [...prev, ...filtered.filter(f => !existing.has(f.name + f.size))];
    });
    setDone(false);
    setFailedFiles([]);
    setDuplicateNames([]);
  }, []);

  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));
  const removeFailedFile = (idx) => setFailedFiles(prev => prev.filter((_, i) => i !== idx));

  /* ── image compression to prevent server OOM ── */
  const compressImage = async (file) => {
    return new Promise((resolve) => {
      if (!file.type.startsWith('image/')) return resolve(file);
      const img = new window.Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const MAX_SIZE = 1920;
        let width = img.width;
        let height = img.height;
        if (width > height) {
          if (width > MAX_SIZE) {
            height = Math.round(height * (MAX_SIZE / width));
            width = MAX_SIZE;
          }
        } else {
          if (height > MAX_SIZE) {
            width = Math.round(width * (MAX_SIZE / height));
            height = MAX_SIZE;
          }
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob((blob) => {
          if (!blob) return resolve(file);
          resolve(new File([blob], file.name, {
            type: file.type === 'image/png' ? 'image/png' : 'image/jpeg',
            lastModified: Date.now(),
          }));
        }, file.type === 'image/png' ? 'image/png' : 'image/jpeg', 0.85);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(file);
      };
      img.src = url;
    });
  };

  /* ── core upload logic ── */
  const runUpload = async (filesToUpload) => {
    setUploading(true);
    setDone(false);

    const batches = [];
    // Reduce batch size to 2 to prevent backend timeout/OOM
    const safeBatchSize = 2; 
    for (let i = 0; i < filesToUpload.length; i += safeBatchSize) {
      batches.push(filesToUpload.slice(i, i + safeBatchSize));
    }

    let accepted       = 0;
    let newFailed      = [];
    let allDuplicates  = [];
    let batchesDone    = 0;

    setProgress({ batchDone: 0, batchTotal: batches.length });

    for (const batch of batches) {
      try {
        const formData = new FormData();
        for (const f of batch) {
            const compressed = await compressImage(f);
            formData.append('files', compressed);
        }

        const { data } = await api.post(
          `/api/photos/events/${eventId}/upload`,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 }
        );

        accepted       += data.accepted   || 0;
        allDuplicates   = [...allDuplicates, ...(data.duplicate_names || [])];

        // If entire batch was rejected (all duplicates or all format errors), don't fail it
        if ((data.accepted || 0) === 0 && (data.duplicates || 0) === 0 && (data.skipped_format || 0) === 0) {
          newFailed = [...newFailed, ...batch];
        }
      } catch {
        newFailed = [...newFailed, ...batch];
      }

      batchesDone++;
      setProgress({ batchDone: batchesDone, batchTotal: batches.length });
    }

    setUploadedCount(prev => prev + accepted);
    setFailedFiles(newFailed);
    setDuplicateNames(allDuplicates);
    setFiles([]);
    setUploading(false);
    setDone(true);

    if (accepted > 0) onUploadComplete?.({ accepted });
  };

  const handleUpload = () => { if (files.length && !uploading) runUpload(files); };
  const handleRetry  = () => { if (failedFiles.length && !uploading) runUpload(failedFiles); };

  const reset = () => {
    setFiles([]); setFailedFiles([]); setDuplicateNames([]);
    setDone(false); setUploadedCount(0);
    setProgress({ batchDone: 0, batchTotal: 0 });
  };

  const pct = progress.batchTotal > 0
    ? Math.round((progress.batchDone / progress.batchTotal) * 100)
    : 0;

  const totalSizeMB = files.reduce((s, f) => s + f.size, 0) / 1024 / 1024;

  /* ── Google Drive import handler ── */
  const handleDriveImport = async () => {
    if (!driveUrl.trim() || driveImporting) return;
    setDriveImporting(true);
    setDriveError('');
    setDriveResult(null);
    try {
      const { data } = await api.post(
        `/api/photos/events/${eventId}/import-drive`,
        { folder_url: driveUrl.trim() },
        { timeout: 30000 }
      );
      setDriveResult(data);
      setDriveUrl('');
      onUploadComplete?.({ accepted: data.queued });
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || 'Import failed';
      setDriveError(msg);
    } finally {
      setDriveImporting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* ── Mode switcher tabs ── */}
      <div style={{ display: 'flex', gap: '0.25rem', background: 'var(--color-surface-2)', padding: '0.35rem', borderRadius: 'var(--radius-pill)', width: 'fit-content', margin: '0 0 1.5rem 0', border: '1px solid var(--border-light)' }}>
        {[
          { id: 'local', icon: <Upload size={14}/>, label: 'Upload from Device' },
          { id: 'drive', icon: <HardDriveDownload size={14}/>, label: 'Import from Google Drive' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => { setUploadMode(tab.id); setDriveResult(null); setDriveError(''); }}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.4rem',
              padding: '0.6rem 1.25rem',
              background: uploadMode === tab.id ? '#ffffff' : 'transparent',
              border: 'none',
              borderRadius: 'var(--radius-pill)',
              boxShadow: uploadMode === tab.id ? '0 2px 8px rgba(0,0,0,0.06), 0 0 0 1px var(--border-light)' : 'none',
              color: uploadMode === tab.id ? 'var(--text-main)' : 'var(--text-muted)',
              fontWeight: uploadMode === tab.id ? 700 : 500,
              fontSize: '0.85rem',
              cursor: 'pointer',
              transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >{tab.icon}{tab.label}</button>
        ))}
      </div>

      {/* ── Google Drive Import Panel ── */}
      {uploadMode === 'drive' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}
        >
          {/* Info card */}
          <div style={{
            background: 'linear-gradient(135deg, rgba(66,133,244,0.08), rgba(52,168,83,0.06))',
            border: '1px solid rgba(66,133,244,0.2)',
            borderRadius: 'var(--radius-lg)',
            padding: '1rem 1.25rem',
            fontSize: '0.85rem',
            color: 'var(--color-text)',
            display: 'flex', flexDirection: 'column', gap: '0.4rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600, color: '#4285F4' }}>
              <svg width="16" height="16" viewBox="0 0 87.3 78" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0a15.92 15.92 0 001.9 7.5l4.7 6.35z" fill="#0066DA"/>
                <path d="M43.65 25L29.9 1.2A15.37 15.37 0 0026.6 4.5L1.9 48.5A15.92 15.92 0 000 56h27.5L43.65 25z" fill="#00AC47"/>
                <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c1.2-2.1 1.9-4.7 1.9-7.5H60.8l5.85 11.5 6.9 15.3z" fill="#EA4335"/>
                <path d="M43.65 25L57.4 1.2C56.05.45 54.5 0 52.85 0H34.45c-1.65 0-3.2.45-4.55 1.2L43.65 25z" fill="#00832D"/>
                <path d="M60.8 56H27.5L13.75 79.8c1.35.75 2.9 1.2 4.55 1.2h50.7c1.65 0 3.2-.45 4.55-1.2L60.8 56z" fill="#2684FC"/>
                <path d="M73.4 27.5l-12.35-21.4A15.37 15.37 0 0057.4 1.2L43.65 25 60.8 56h27.45c0-2.8-.7-5.4-1.9-7.5L73.4 27.5z" fill="#FFBA00"/>
              </svg>
              Import from Google Drive
            </div>
            <div style={{ color: 'var(--color-muted)', lineHeight: 1.5 }}>
              Paste a shared folder link. The folder must be set to <strong>"Anyone with the link - Viewer"</strong>.
              All images inside will be imported automatically.
            </div>
            <div style={{ color: 'var(--color-muted)', fontSize: '0.8rem' }}>
              ✅ Supports: JPEG / JPG only &nbsp;|&nbsp; ✅ Auto dedup (same file won't be imported twice)
            </div>
          </div>

          {/* URL Input */}
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'stretch' }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <Link size={15} style={{
                position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)',
                color: 'var(--color-muted)',
              }}/>
              <input
                type="url"
                placeholder="https://drive.google.com/drive/folders/..."
                value={driveUrl}
                onChange={e => { setDriveUrl(e.target.value); setDriveError(''); setDriveResult(null); }}
                onKeyDown={e => e.key === 'Enter' && handleDriveImport()}
                style={{
                  width: '100%',
                  padding: '0.7rem 0.9rem 0.7rem 2.4rem',
                  border: driveError ? '1.5px solid var(--error)' : '1.5px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--color-surface-2)',
                  color: 'var(--color-text)',
                  fontSize: '0.875rem',
                  outline: 'none',
                  boxSizing: 'border-box',
                  transition: 'border 0.2s',
                }}
              />
            </div>
            <button
              onClick={handleDriveImport}
              disabled={!driveUrl.trim() || driveImporting}
              className="btn btn-primary btn-pill"
              style={{ whiteSpace: 'nowrap', minWidth: '140px', display: 'flex', alignItems: 'center', gap: '0.4rem', boxShadow: '0 4px 12px rgba(91, 95, 239, 0.2)' }}
            >
              {driveImporting
                ? <><Loader2 size={14} className="spin"/>Importing…</>
                : <><FolderOpen size={14}/>Import Photos</>
              }
            </button>
          </div>

          {/* Error */}
          {driveError && (
            <div style={{
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: 'var(--radius-md)', padding: '0.75rem 1rem',
              color: 'var(--error)', fontSize: '0.85rem', display: 'flex', gap: '0.5rem', alignItems: 'flex-start',
            }}>
              <AlertCircle size={15} style={{ marginTop: 2, flexShrink: 0 }}/>
              <span>{driveError}</span>
            </div>
          )}

          {/* Success result */}
          {driveResult && (
            <motion.div
              initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
              style={{
                background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.25)',
                borderRadius: 'var(--radius-lg)', padding: '1rem 1.25rem',
                display: 'flex', flexDirection: 'column', gap: '0.6rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600, color: 'var(--success)' }}>
                <CheckCircle2 size={16}/>
                {driveResult.queued} photos queued for import!
              </div>
              <div style={{ color: 'var(--color-muted)', fontSize: '0.82rem' }}>
                Photos are downloading and processing in the background. Check the <strong>Photos</strong> tab in a moment.
              </div>
              {driveResult.files?.length > 0 && (
                <div style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>
                  First files: {driveResult.files.join(', ')}{driveResult.queued > 10 ? ` +${driveResult.queued - 10} more…` : ''}
                </div>
              )}
            </motion.div>
          )}

          {/* ── How-to guide ── */}
          <div style={{
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--color-border)',
            overflow: 'hidden',
          }}>
            {/* Header */}
            <div style={{
              background: 'linear-gradient(90deg, rgba(66,133,244,0.12), rgba(52,168,83,0.08))',
              padding: '0.65rem 1rem',
              borderBottom: '1px solid var(--color-border)',
              display: 'flex', alignItems: 'center', gap: '0.5rem',
            }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text)', letterSpacing: '0.02em' }}>
                📋 HOW TO SHARE A GOOGLE DRIVE FOLDER
              </span>
            </div>

            {/* Steps */}
            <div style={{ display: 'flex', flexDirection: 'column', background: 'var(--color-surface-2)' }}>
              {[
                {
                  num: '1',
                  text: <>Open <strong>Google Drive</strong> and navigate to your photos folder</>,
                  sub: null,
                  warn: false,
                },
                {
                  num: '2',
                  text: <>Right-click the folder and click <strong style={{ color: 'var(--accent)' }}>"Share"</strong></>,
                  sub: null,
                  warn: false,
                },
                {
                  num: '3',
                  text: <>Under <em>"General access"</em>, click the dropdown and choose <strong style={{ color: '#ea4335' }}>"Anyone with the link"</strong></>,
                  sub: (
                    <div style={{
                      marginTop: '0.4rem',
                      background: 'rgba(234,67,53,0.08)',
                      border: '1px solid rgba(234,67,53,0.25)',
                      borderRadius: '6px',
                      padding: '0.4rem 0.65rem',
                      fontSize: '0.78rem',
                      color: '#ea4335',
                      display: 'flex', alignItems: 'center', gap: '0.4rem',
                    }}>
                      ⚠️ <span>This step is <strong>required</strong>. Private folders cannot be imported</span>
                    </div>
                  ),
                  warn: true,
                },
                {
                  num: '4',
                  text: <>Make sure the role is set to <strong style={{ color: 'var(--success)' }}>"Viewer"</strong> (not Editor)</>,
                  sub: null,
                  warn: false,
                },
                {
                  num: '5',
                  text: <>Click <strong style={{ color: 'var(--accent)' }}>"Copy link"</strong> and paste it in the field above</>,
                  sub: null,
                  warn: false,
                },
              ].map((step, i, arr) => (
                <div key={i} style={{
                  display: 'flex', gap: '0.75rem',
                  padding: '0.75rem 1rem',
                  borderBottom: i < arr.length - 1 ? '1px solid var(--color-border)' : 'none',
                  background: step.warn ? 'rgba(234,67,53,0.03)' : 'transparent',
                }}>
                  {/* Step number bubble */}
                  <div style={{
                    width: 22, height: 22, borderRadius: '50%',
                    background: step.warn ? '#ea4335' : 'var(--accent)',
                    color: '#fff',
                    fontSize: '0.7rem', fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0, marginTop: 1,
                  }}>{step.num}</div>

                  {/* Step text */}
                  <div style={{ flex: 1, fontSize: '0.84rem', color: 'var(--color-text)', lineHeight: 1.55 }}>
                    {step.text}
                    {step.sub}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      )}

      {/* ── Drop zone ── */}
      {uploadMode === 'local' && !done && (
        <div
          style={{
            border: `1.5px dashed ${dragOver ? 'var(--primary)' : 'var(--border-dark)'}`,
            borderRadius: 'var(--radius-md)',
            background: dragOver ? 'rgba(91,95,239,0.04)' : '#fafafa',
            padding: '5rem 2rem',
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
            accept="image/jpeg,image/jpg,.jpg,.jpeg"
            style={{ display: 'none' }}
            onChange={(e) => addFiles(e.target.files)}
          />
          <h3 style={{ margin: '0 0 0.6rem 0', fontSize: '1.15rem', color: 'var(--text-main)', fontWeight: 700 }}>
            Drop photos here or browse
          </h3>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            JPEG / JPG only &nbsp;·&nbsp; Max 25 MB each &nbsp;·&nbsp; Batches of {BATCH_SIZE}
          </p>
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
              You can switch tabs, upload will continue in the background
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
            {/* Duplicate files panel */}
            {duplicateNames.length > 0 && (
              <div style={{
                background: '#fff', border: '1px solid rgba(217,119,6,0.3)',
                borderRadius: 'var(--radius-lg)', overflow: 'hidden',
                marginBottom: failedFiles.length > 0 ? '0.875rem' : 0,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '0.875rem 1.125rem',
                  background: 'rgba(217,119,6,0.06)',
                  borderBottom: '1px solid rgba(217,119,6,0.15)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ fontSize: '1rem' }}>⚠️</span>
                    <span style={{ fontWeight: 700, fontSize: '0.875rem', color: '#92400e' }}>
                      {duplicateNames.length} photo{duplicateNames.length !== 1 ? 's' : ''} already exist in this event
                    </span>
                  </div>
                  <button className="btn btn-ghost btn-sm" onClick={() => setDuplicateNames([])}>
                    <X size={12} /> Dismiss
                  </button>
                </div>
                <div style={{ padding: '0.5rem 0', maxHeight: 180, overflowY: 'auto' }}>
                  {duplicateNames.map((name, i) => (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'center', gap: '0.625rem',
                      padding: '0.5rem 1.125rem',
                      background: i % 2 === 0 ? 'transparent' : 'rgba(217,119,6,0.02)',
                    }}>
                      <div style={{ width: 28, height: 28, borderRadius: '7px', background: 'rgba(217,119,6,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        <span style={{ fontSize: '0.75rem' }}>🔁</span>
                      </div>
                      <span style={{ fontSize: '0.8375rem', color: '#92400e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                        {name}
                      </span>
                      <span style={{ fontSize: '0.7rem', color: '#b45309', background: 'rgba(217,119,6,0.1)', padding: '0.1rem 0.5rem', borderRadius: '999px', whiteSpace: 'nowrap' }}>
                        Already uploaded
                      </span>
                    </div>
                  ))}
                </div>
                <div style={{ padding: '0.625rem 1.125rem', borderTop: '1px solid rgba(217,119,6,0.12)', background: 'rgba(217,119,6,0.03)' }}>
                  <p style={{ fontSize: '0.75rem', color: '#92400e' }}>
                    💡 Detected using SHA-256 file hash. Same file content, even if renamed
                  </p>
                </div>
              </div>
            )}

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
            className="btn btn-primary btn-pill"
            disabled={!files.length || uploading}
            onClick={handleUpload}
            style={{ padding: '0.65rem 1.5rem', boxShadow: '0 4px 12px rgba(91, 95, 239, 0.2)' }}
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
