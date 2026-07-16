import { useRef, useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, CloudUpload, X, CheckCircle2, AlertCircle,
  Loader2, Image, RefreshCw, RotateCcw, FileWarning,
  FolderOpen, Link, HardDriveDownload, Activity
} from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';

const UPLOAD_PAGE_MAX_FILES = 2;
const UPLOAD_PAGE_MAX_BYTES = 128 * 1024 * 1024;
const CONCURRENCY_LIMIT = 2;
const MAX_FILE_SIZE_MB = 100;
const PENDING_SEAL_KEY_PREFIX = 'pg_pending_batch_seal_v1:';
const PENDING_SEAL_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const INTERRUPTED_UPLOAD_GRACE_MS = 15 * 60 * 1000;
const SEAL_RETRY_DELAYS_MS = [0, 1000, 3000];
const sealRequests = new Map();

function buildUploadPages(filesToUpload) {
  const pages = [];
  let page = [];
  let pageBytes = 0;

  filesToUpload.forEach((file) => {
    const exceedsPageLimit = page.length > 0 && (
      page.length >= UPLOAD_PAGE_MAX_FILES
      || pageBytes + file.size > UPLOAD_PAGE_MAX_BYTES
    );
    if (exceedsPageLimit) {
      pages.push(page);
      page = [];
      pageBytes = 0;
    }
    page.push(file);
    pageBytes += file.size;
  });

  if (page.length) pages.push(page);
  return pages;
}

function readPendingSeals() {
  try {
    const now = Date.now();
    const entries = [];
    const expiredKeys = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(PENDING_SEAL_KEY_PREFIX)) continue;
      try {
        const entry = JSON.parse(localStorage.getItem(key));
        const isFresh = entry?.batchId
          && entry?.eventId
          && now - Number(entry.updatedAt || 0) < PENDING_SEAL_MAX_AGE_MS;
        if (isFresh) entries.push(entry);
        else expiredKeys.push(key);
      } catch {
        expiredKeys.push(key);
      }
    }
    expiredKeys.forEach((key) => localStorage.removeItem(key));
    return entries;
  } catch {
    return [];
  }
}

function rememberPendingSeal(entry) {
  try {
    localStorage.setItem(
      `${PENDING_SEAL_KEY_PREFIX}${entry.batchId}`,
      JSON.stringify({ ...entry, updatedAt: Date.now() }),
    );
  } catch {
    // Uploading still works when storage is unavailable; only crash recovery degrades.
  }
}

function forgetPendingSeal(batchId) {
  try {
    localStorage.removeItem(`${PENDING_SEAL_KEY_PREFIX}${batchId}`);
  } catch {
    // The entry will expire naturally if browser storage cannot be updated.
  }
}

function touchPendingSeal(batchId) {
  try {
    const key = `${PENDING_SEAL_KEY_PREFIX}${batchId}`;
    const entry = JSON.parse(localStorage.getItem(key));
    if (entry?.batchId) {
      localStorage.setItem(key, JSON.stringify({ ...entry, updatedAt: Date.now() }));
    }
  } catch {
    // Best-effort lease heartbeat; recovery still has a conservative grace period.
  }
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const fileKey = (file) => `${file.name}::${file.size}`;

// Client-side pipeline steps for one file. Once the file is accepted by the
// server it continues as a Photo row: P: Queued → Processing → Processed.
const FILE_STAGES = {
  u_queued: { label: 'U: Queued', title: 'Upload is queued' },
  uploading: { label: 'Uploading', title: 'Uploading to server' },
  p_queued: { label: 'Uploaded · P: Queued', title: 'Uploaded — face processing queued' },
  failed: { label: 'Upload failed', title: 'This file did not reach the server' },
};

const initialUploadTelemetry = {
  activeNames: [],
  uploadedBytes: 0,
  totalBytes: 0,
  speedBps: 0,
};

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function formatSpeed(bytesPerSecond) {
  return `${formatBytes(bytesPerSecond)}/s`;
}

function sealProcessingBatch(batchId) {
  if (sealRequests.has(batchId)) return sealRequests.get(batchId);

  const request = (async () => {
    let lastError;
    for (const delay of SEAL_RETRY_DELAYS_MS) {
      if (delay) await wait(delay);
      try {
        const { data } = await api.post(`/api/photos/batches/${batchId}/seal`, {}, { timeout: 15000 });
        forgetPendingSeal(batchId);
        return data;
      } catch (error) {
        lastError = error;
        const status = error?.response?.status;
        if (status === 401 || status === 403 || status === 404) break;
      }
    }
    throw lastError;
  })().finally(() => sealRequests.delete(batchId));

  sealRequests.set(batchId, request);
  return request;
}

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
  const [rejectedFiles, setRejectedFiles] = useState([]);
  const [uploadError, setUploadError] = useState('');
  const [batchTrackingWarning, setBatchTrackingWarning] = useState('');
  const [activeBatchId, setActiveBatchId] = useState(null);
  const [uploadTelemetry, setUploadTelemetry] = useState(initialUploadTelemetry);
  // fileKey -> 'u_queued' | 'uploading' | 'p_queued' | 'failed'
  const [fileStages, setFileStages] = useState({});

  // Google Drive state
  const [driveUrl, setDriveUrl]           = useState('');
  const [driveImporting, setDriveImporting] = useState(false);
  const [driveResult, setDriveResult]     = useState(null);  // { queued, message, files }
  const [driveError, setDriveError]       = useState('');

  const inputRef = useRef(null);
  const activeUploadBatchRef = useRef(null);
  const pageProgressRef = useRef(new Map());
  const completedBytesRef = useRef(0);
  const lastUploadSampleRef = useRef({ bytes: 0, at: 0 });

  useEffect(() => {
    let disposed = false;
    let recovering = false;

    const recoverPendingSeals = async () => {
      if (recovering) return;
      recovering = true;
      try {
        if (activeUploadBatchRef.current) touchPendingSeal(activeUploadBatchRef.current);
        const now = Date.now();
        const pending = readPendingSeals().filter((entry) => String(entry.eventId) === String(eventId));
        for (const entry of pending) {
          if (entry.batchId === activeUploadBatchRef.current) continue;
          const interruptedUploadIsRecent = entry.stage === 'uploading'
            && now - Number(entry.updatedAt || 0) < INTERRUPTED_UPLOAD_GRACE_MS;
          if (interruptedUploadIsRecent) continue;
          try {
            await sealProcessingBatch(entry.batchId);
          } catch (error) {
            const status = error?.response?.status;
            if (status === 403 || status === 404) {
              forgetPendingSeal(entry.batchId);
              continue;
            }
            if (!disposed && status !== 401) {
              setBatchTrackingWarning(
                `${getApiErrorMessage(error, 'A previous batch is still waiting to be finalized.')} It will retry automatically.`,
              );
            }
          }
        }
      } finally {
        recovering = false;
      }
    };

    recoverPendingSeals();
    const recoveryTimer = setInterval(recoverPendingSeals, 60000);
    window.addEventListener('online', recoverPendingSeals);
    return () => {
      disposed = true;
      clearInterval(recoveryTimer);
      window.removeEventListener('online', recoverPendingSeals);
    };
  }, [eventId]);

  /* ── file selection ── */
  const addFiles = useCallback((newFiles) => {
    const validTypes = ['image/jpeg', 'image/jpg'];
    const accepted = [];
    const rejected = [];
    Array.from(newFiles).forEach((file) => {
      const lowerName = file.name.toLowerCase();
      const isJpeg = validTypes.includes(file.type) || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg');
      if (!isJpeg) {
        rejected.push({ name: file.name, reason: 'Only JPEG or JPG photos are supported' });
      } else if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
        rejected.push({ name: file.name, reason: `Larger than ${MAX_FILE_SIZE_MB} MB` });
      } else {
        accepted.push(file);
      }
    });
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size));
      return [...prev, ...accepted.filter(f => !existing.has(f.name + f.size))];
    });
    if (rejected.length) setRejectedFiles(prev => [...prev, ...rejected]);
    setDone(false);
    setFailedFiles([]);
    setDuplicateNames([]);
    setUploadError('');
  }, []);

  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));
  const removeFailedFile = (idx) => setFailedFiles(prev => prev.filter((_, i) => i !== idx));

  const createProcessingBatch = async (filesToUpload, source) => {
    try {
      const totalBytes = filesToUpload.reduce((sum, file) => sum + file.size, 0);
      const normalizedSource = source === 'retry' ? 'retry' : 'upload';
      const { data } = await api.post(
        `/api/photos/events/${eventId}/batches`,
        {
          source: normalizedSource,
          expected_images: filesToUpload.length,
          total_images: filesToUpload.length,
          total_bytes: totalBytes,
        },
        { timeout: 15000 },
      );
      const batchId = data?.batch_id || data?.id;
      setActiveBatchId(batchId || null);
      setBatchTrackingWarning(batchId ? '' : 'Upload will continue, but live batch tracking is unavailable.');
      if (batchId) {
        rememberPendingSeal({
          batchId,
          eventId,
          source: normalizedSource,
          stage: 'uploading',
        });
      }
      return batchId || null;
    } catch (error) {
      setActiveBatchId(null);
      const status = error?.response?.status;
      if (status === 404 || status === 405 || status === 501) {
        setBatchTrackingWarning('Upload will continue using server-managed pages without live batch tracking.');
        return null;
      }
      throw error;
    }
  };

  const setStageForFiles = (pageFiles, stage) => {
    setFileStages((prev) => {
      const next = { ...prev };
      pageFiles.forEach((file) => { next[fileKey(file)] = stage; });
      return next;
    });
  };

  const runUpload = async (filesToUpload, source = 'upload') => {
    const uploadTotalBytes = filesToUpload.reduce((sum, file) => sum + file.size, 0);
    pageProgressRef.current = new Map();
    completedBytesRef.current = 0;
    lastUploadSampleRef.current = { bytes: 0, at: performance.now() };
    setFileStages(Object.fromEntries(filesToUpload.map((file) => [fileKey(file), 'u_queued'])));
    setUploading(true);
    setDone(false);
    setUploadError('');
    setBatchTrackingWarning('');
    setActiveBatchId(null);
    setUploadTelemetry({
      activeNames: [],
      uploadedBytes: 0,
      totalBytes: uploadTotalBytes,
      speedBps: 0,
    });
    activeUploadBatchRef.current = null;

    let serverBatchId = null;
    try {
      serverBatchId = await createProcessingBatch(filesToUpload, source);
      activeUploadBatchRef.current = serverBatchId;
    } catch (error) {
      setUploadError(getApiErrorMessage(error, 'Could not start this upload.'));
      setFailedFiles(filesToUpload);
      setUploading(false);
      setDone(true);
      activeUploadBatchRef.current = null;
      return;
    }

    const pages = buildUploadPages(filesToUpload);

    let accepted       = 0;
    let newFailed      = [];
    let allDuplicates  = [];
    let pagesDone      = 0;
    const implicitBatchIds = new Set();

    setProgress({ batchDone: 0, batchTotal: pages.length });

    const executing = new Set();

    for (const page of pages) {
      const promise = (async () => {
        const pageKey = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const pageBytes = page.reduce((sum, file) => sum + file.size, 0);
        const pageNames = page.map((file) => file.name);
        setStageForFiles(page, 'uploading');
        pageProgressRef.current.set(pageKey, 0);
        setUploadTelemetry(prev => ({
          ...prev,
          activeNames: pageNames,
        }));
        try {
          if (serverBatchId) {
            rememberPendingSeal({ batchId: serverBatchId, eventId, source, stage: 'uploading' });
          }
          const formData = new FormData();
          for (const f of page) {
            // Preserve the original image bytes and metadata for maximum face detail.
            formData.append('files', f);
          }
          if (serverBatchId) formData.append('batch_id', serverBatchId);

          const { data } = await api.post(
            `/api/photos/events/${eventId}/upload`,
            formData,
            {
              headers: { 'Content-Type': 'multipart/form-data' },
              params: serverBatchId ? { batch_id: serverBatchId } : undefined,
              timeout: 0,
              onUploadProgress: (event) => {
                const loaded = Math.min(Number(event.loaded || 0), pageBytes);
                pageProgressRef.current.set(pageKey, loaded);
                const activeLoaded = Array.from(pageProgressRef.current.values())
                  .reduce((sum, value) => sum + Number(value || 0), 0);
                const totalLoaded = Math.min(uploadTotalBytes, completedBytesRef.current + activeLoaded);
                const now = performance.now();
                const last = lastUploadSampleRef.current;
                const elapsedSeconds = Math.max(0.1, (now - last.at) / 1000);
                const speedBps = Math.max(0, (totalLoaded - last.bytes) / elapsedSeconds);
                lastUploadSampleRef.current = { bytes: totalLoaded, at: now };
                setUploadTelemetry({
                  activeNames: pageNames,
                  uploadedBytes: totalLoaded,
                  totalBytes: uploadTotalBytes,
                  speedBps,
                });
              },
            }
          );

          accepted       += data.accepted   || 0;
          allDuplicates   = [...allDuplicates, ...(data.duplicate_names || [])];
          if (!serverBatchId && data?.batch_id) implicitBatchIds.add(data.batch_id);

          // If the entire page was rejected without a reason, keep it available for retry.
          if ((data.accepted || 0) === 0 && (data.duplicates || 0) === 0 && (data.skipped_format || 0) === 0) {
            newFailed = [...newFailed, ...page];
            setStageForFiles(page, 'failed');
          } else {
            setStageForFiles(page, 'p_queued');
          }
        } catch {
          newFailed = [...newFailed, ...page];
          setStageForFiles(page, 'failed');
        } finally {
          const loaded = Number(pageProgressRef.current.get(pageKey) || 0);
          completedBytesRef.current = Math.min(uploadTotalBytes, completedBytesRef.current + Math.max(pageBytes, loaded));
          pageProgressRef.current.delete(pageKey);
          const activeLoaded = Array.from(pageProgressRef.current.values())
            .reduce((sum, value) => sum + Number(value || 0), 0);
          setUploadTelemetry(prev => ({
            ...prev,
            activeNames: [],
            uploadedBytes: Math.min(uploadTotalBytes, completedBytesRef.current + activeLoaded),
          }));
        }

        pagesDone++;
        setProgress(prev => ({ ...prev, batchDone: pagesDone }));
      })();

      executing.add(promise);
      promise.finally(() => executing.delete(promise));

      if (executing.size >= CONCURRENCY_LIMIT) {
        await Promise.race(executing);
      }
    }

    // Wait for all remaining batches to finish
    await Promise.all(executing);

    if (serverBatchId) {
      rememberPendingSeal({ batchId: serverBatchId, eventId, source, stage: 'ready' });
      try {
        await sealProcessingBatch(serverBatchId);
      } catch (error) {
        setBatchTrackingWarning(
          `${getApiErrorMessage(error, 'Photos uploaded, but this batch is still waiting to be finalized.')} It will retry automatically.`,
        );
      }
    }

    const trackedBatchId = serverBatchId || (implicitBatchIds.size === 1 ? [...implicitBatchIds][0] : null);
    setActiveBatchId(trackedBatchId);
    activeUploadBatchRef.current = null;

    setUploadedCount(prev => prev + accepted);
    setFailedFiles(newFailed);
    setDuplicateNames(allDuplicates);
    setFiles([]);
    setUploading(false);
    setDone(true);
    setUploadTelemetry(prev => ({
      ...prev,
      activeNames: [],
      uploadedBytes: Math.max(prev.uploadedBytes, accepted > 0 ? uploadTotalBytes : prev.uploadedBytes),
      speedBps: 0,
    }));

    if (accepted > 0) onUploadComplete?.({ accepted, batchId: trackedBatchId, batch_id: trackedBatchId });
  };

  const handleUpload = () => { if (files.length && !uploading) runUpload(files); };
  const handleRetry  = () => { if (failedFiles.length && !uploading) runUpload(failedFiles, 'retry'); };

  const reset = () => {
    setFiles([]); setFailedFiles([]); setDuplicateNames([]); setRejectedFiles([]);
    setDone(false); setUploadedCount(0);
    setProgress({ batchDone: 0, batchTotal: 0 });
    setUploadError(''); setBatchTrackingWarning(''); setActiveBatchId(null);
    setUploadTelemetry(initialUploadTelemetry);
    setFileStages({});
  };

  const pct = progress.batchTotal > 0
    ? Math.round((progress.batchDone / progress.batchTotal) * 100)
    : 0;

  const totalSizeMB = files.reduce((s, f) => s + f.size, 0) / 1024 / 1024;
  const uploadPageCount = buildUploadPages(files).length;

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
        { timeout: 300000 }   // 5 min — large Drive folders (1000+ files) can be slow to list
      );
      setDriveResult(data);
      setDriveUrl('');
      const batchId = data?.batch_id || data?.id || null;
      setActiveBatchId(batchId);
      onUploadComplete?.({ accepted: data.queued, batchId, batch_id: batchId });
    } catch (err) {
      setDriveError(getApiErrorMessage(err, 'Import failed'));
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

      {uploadMode === 'local' && uploading && (
        <div className="card" style={{ padding: '0.9rem 1rem', borderColor: 'rgba(6,182,212,0.28)', background: 'rgba(6,182,212,0.06)' }}>
          <div style={{ alignItems: 'center', display: 'grid', gap: '0.75rem', gridTemplateColumns: 'minmax(0, 1.5fr) repeat(3, minmax(120px, 0.55fr))' }}>
            <div style={{ minWidth: 0 }}>
              <div className="text-xs text-muted" style={{ alignItems: 'center', display: 'flex', gap: '0.35rem', marginBottom: 2 }}>
                <Activity size={13} /> Currently uploading
              </div>
              <div className="text-sm font-semibold truncate" title={uploadTelemetry.activeNames.join(', ') || 'Preparing upload'}>
                {uploadTelemetry.activeNames.length ? uploadTelemetry.activeNames.join(', ') : 'Preparing upload'}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Speed</div>
              <div className="text-sm font-semibold">{formatSpeed(uploadTelemetry.speedBps)}</div>
            </div>
            <div>
              <div className="text-xs text-muted">Uploaded</div>
              <div className="text-sm font-semibold">
                {formatBytes(uploadTelemetry.uploadedBytes)} / {formatBytes(uploadTelemetry.totalBytes)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Page</div>
              <div className="text-sm font-semibold">{Math.min(progress.batchDone + 1, progress.batchTotal)} of {progress.batchTotal}</div>
            </div>
          </div>
          <div className="progress-bar" style={{ height: 5, marginTop: '0.75rem' }}>
            <div
              className="progress-bar-fill"
              style={{
                width: `${uploadTelemetry.totalBytes > 0 ? Math.min(100, (uploadTelemetry.uploadedBytes / uploadTelemetry.totalBytes) * 100) : 0}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* ── Per-file pipeline stages (U: Queued → Uploading → Uploaded · P: Queued) ── */}
      {uploadMode === 'local' && Object.keys(fileStages).length > 0 && (uploading || done) && (
        <div style={{ background: '#fff', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <div style={{ alignItems: 'center', background: 'var(--color-surface-2)', borderBottom: '1px solid var(--color-border)', display: 'flex', gap: '0.5rem', justifyContent: 'space-between', padding: '0.65rem 1rem' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700 }}>Upload pipeline</span>
            <span className="text-xs text-muted">
              U = upload · P = processing. Processing continues in the Photos tab
              (P: Queued → Processing → Processed).
            </span>
          </div>
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {Object.entries(fileStages).map(([key, stage]) => {
              const name = key.slice(0, key.lastIndexOf('::'));
              const meta = FILE_STAGES[stage] || FILE_STAGES.u_queued;
              return (
                <div key={key} style={{ alignItems: 'center', borderBottom: '1px solid var(--color-border)', display: 'flex', gap: '0.75rem', justifyContent: 'space-between', padding: '0.45rem 1rem' }}>
                  <span className="truncate" style={{ flex: 1, fontSize: '0.8rem', minWidth: 0 }} title={name}>{name}</span>
                  <span className={`upload-stage-chip upload-stage-${stage}`} title={meta.title}>
                    {stage === 'uploading' && <Loader2 size={11} className="spin" style={{ animation: 'spin 1s linear infinite' }} />}
                    {meta.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {uploadError && (
        <div style={{ alignItems: 'center', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', color: 'var(--error)', display: 'flex', fontSize: '0.82rem', gap: '0.5rem', padding: '0.75rem 1rem' }} role="alert">
          <AlertCircle size={15} /> {uploadError}
        </div>
      )}

      {batchTrackingWarning && (
        <div style={{ alignItems: 'center', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.22)', borderRadius: 'var(--radius-md)', color: '#92400e', display: 'flex', fontSize: '0.78rem', gap: '0.5rem', padding: '0.7rem 1rem' }}>
          <AlertCircle size={14} /> {batchTrackingWarning}
        </div>
      )}

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
            onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
          />
          <h3 style={{ margin: '0 0 0.6rem 0', fontSize: '1.15rem', color: 'var(--text-main)', fontWeight: 700 }}>
            Drop photos here or browse
          </h3>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            JPEG / JPG only &nbsp;·&nbsp; Max {MAX_FILE_SIZE_MB} MB each &nbsp;·&nbsp; Originals are preserved
          </p>
        </div>
      )}

      {uploadMode === 'local' && rejectedFiles.length > 0 && (
        <div style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.22)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
          <div style={{ alignItems: 'center', display: 'flex', justifyContent: 'space-between', padding: '0.75rem 1rem' }}>
            <span style={{ alignItems: 'center', color: '#92400e', display: 'flex', fontSize: '0.82rem', fontWeight: 700, gap: '0.45rem' }}>
              <FileWarning size={15} /> {rejectedFiles.length} file{rejectedFiles.length === 1 ? '' : 's'} not added
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => setRejectedFiles([])}><X size={12} /> Dismiss</button>
          </div>
          <div style={{ borderTop: '1px solid rgba(245,158,11,0.18)', maxHeight: 150, overflowY: 'auto' }}>
            {rejectedFiles.map((item, index) => (
              <div key={`${item.name}-${index}`} style={{ display: 'flex', fontSize: '0.75rem', gap: '0.75rem', justifyContent: 'space-between', padding: '0.5rem 1rem' }}>
                <span className="truncate" style={{ color: 'var(--text-main)' }}>{item.name}</span>
                <span style={{ color: '#92400e', flexShrink: 0 }}>{item.reason}</span>
              </div>
            ))}
          </div>
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
                  Uploading original page {Math.min(progress.batchDone + 1, progress.batchTotal)} of {progress.batchTotal}…
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
              Face processing starts as each page reaches the server. Interrupted batch finalization recovers automatically.
              {activeBatchId && <> Live batch <code>{String(activeBatchId).slice(0, 8)}</code></>}
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
                    Face detection and People grouping are now running in the background
                    {activeBatchId && <> · Live batch <code>{String(activeBatchId).slice(0, 8)}</code></>}
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
                        onClick={() => runUpload([f], 'retry')}
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
              {uploadPageCount} upload page{uploadPageCount === 1 ? '' : 's'} · up to {UPLOAD_PAGE_MAX_FILES} photos and 128 MB per page
            </span>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
