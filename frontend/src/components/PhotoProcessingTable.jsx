import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Ban, ChevronLeft, ChevronRight, Eye, Loader2, Play, RefreshCw,
  ScanFace, Search, Trash2, Upload, X
} from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import { photoStage } from '../lib/statusSteps';

const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  { value: 'queued', label: 'Queued (U/P)' },
  { value: 'processing', label: 'Processing' },
  { value: 'failed', label: 'Failed' },
  { value: 'done', label: 'Processed' },
];

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function StatusBadge({ photo }) {
  const stage = photoStage(photo);
  return <span className={`badge ${stage.cls}`} title={stage.title}>{stage.label}</span>;
}

// Preview image with face bounding boxes; each box shows the person's name
// above it on hover. Boxes use percentage offsets against the image's natural
// dimensions, so they track the rendered size automatically.
function FaceOverlayImage({ photo }) {
  const [faces, setFaces] = useState([]);
  const [natural, setNatural] = useState(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [facesError, setFacesError] = useState('');
  const src = photo.preview_url || photo.thumbnail_url;

  useEffect(() => {
    let cancelled = false;
    setFaces([]);
    setNatural(null);
    setFacesError('');
    if (photo.status !== 'done') return undefined;
    (async () => {
      try {
        const { data } = await api.get(`/api/photos/${photo.id}/faces`);
        if (!cancelled) setFaces(data.faces || []);
      } catch (err) {
        if (!cancelled) setFacesError(getApiErrorMessage(err, 'Could not load detected faces.'));
      }
    })();
    return () => { cancelled = true; };
  }, [photo.id, photo.status]);

  const personName = (face, index) => face.person_label
    || (face.cluster_id ? `Person ${face.cluster_id.slice(0, 4)}` : `Face ${index + 1}`);

  const boxes = natural && showBoxes ? faces.map((face, index) => {
    const { x1, y1, x2, y2 } = face.bbox || {};
    const width = Math.max(0, (x2 - x1) / natural.width) * 100;
    const height = Math.max(0, (y2 - y1) / natural.height) * 100;
    if (!width || !height) return null;
    return (
      <div
        key={face.id}
        className={`face-box${face.is_low_quality ? ' face-box-lowq' : ''}`}
        style={{
          left: `${(x1 / natural.width) * 100}%`,
          top: `${(y1 / natural.height) * 100}%`,
          width: `${width}%`,
          height: `${height}%`,
        }}
      >
        <span className="face-box-name">
          {personName(face, index)}
          {face.is_low_quality ? ' · low quality' : ''}
        </span>
      </div>
    );
  }) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem', maxWidth: '100%' }}>
      <div className="face-overlay-wrap">
        <img
          src={src}
          alt={photo.filename}
          onLoad={(event) => setNatural({
            width: event.target.naturalWidth || 1,
            height: event.target.naturalHeight || 1,
          })}
        />
        {boxes}
      </div>
      <div style={{ alignItems: 'center', display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center' }}>
        {photo.status === 'done' && (
          <button
            className="btn btn-ghost btn-sm face-overlay-toggle"
            onClick={() => setShowBoxes((value) => !value)}
            disabled={!faces.length}
          >
            <ScanFace size={13} />
            {faces.length
              ? `${showBoxes ? 'Hide' : 'Show'} ${faces.length} face${faces.length === 1 ? '' : 's'}`
              : 'No faces detected'}
          </button>
        )}
        {facesError && <span className="text-xs" style={{ color: 'var(--error)' }}>{facesError}</span>}
      </div>
    </div>
  );
}

export default function PhotoProcessingTable({
  eventId,
  onChanged,
  onUploadNow,
}) {
  const [photos, setPhotos] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busyAction, setBusyAction] = useState('');
  const [preview, setPreview] = useState(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const offset = (page - 1) * pageSize;
  const visibleRange = useMemo(() => {
    if (!total) return '0';
    return `${offset + 1}-${Math.min(offset + photos.length, total)}`;
  }, [offset, photos.length, total]);

  const loadPhotos = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await api.get(`/api/photos/events/${eventId}`, {
        params: {
          skip: (page - 1) * pageSize,
          limit: pageSize,
          status_filter: statusFilter,
          q: query.trim() || undefined,
        },
      });
      setPhotos(data.photos || []);
      setTotal(Number(data.total || 0));
    } catch (err) {
      setError(getApiErrorMessage(err, 'Could not load photos.'));
    } finally {
      setLoading(false);
    }
  }, [eventId, page, pageSize, statusFilter, query]);

  useEffect(() => {
    const timer = setTimeout(loadPhotos, query.trim() ? 250 : 0);
    return () => clearTimeout(timer);
  }, [loadPhotos, query]);

  useEffect(() => {
    setPage(1);
  }, [eventId, pageSize, statusFilter, query]);

  useEffect(() => {
    const hasActiveRows = photos.some((photo) => photo.status === 'queued' || photo.status === 'processing');
    if (!hasActiveRows) return undefined;
    const timer = setInterval(loadPhotos, 4000);
    return () => clearInterval(timer);
  }, [photos, loadPhotos]);

  const refreshAfterAction = async () => {
    await loadPhotos();
    onChanged?.();
  };

  const runRowAction = async (photo, action) => {
    const key = `${action}:${photo.id}`;
    setBusyAction(key);
    setError('');
    try {
      if (action === 'process') {
        await api.post(`/api/photos/${photo.id}/process-now`);
      } else if (action === 'cancel') {
        await api.post(`/api/photos/${photo.id}/cancel`);
      } else if (action === 'remove') {
        if (!window.confirm(`Remove ${photo.filename}? This deletes the photo and related face data.`)) return;
        await api.delete(`/api/photos/${photo.id}`);
      }
      await refreshAfterAction();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Photo action failed.'));
    } finally {
      setBusyAction('');
    }
  };

  const runPageAction = async (action) => {
    const candidates = photos.filter((photo) => {
      if (action === 'process') return photo.status !== 'processing';
      if (action === 'cancel') return photo.status === 'queued' || photo.status === 'processing';
      return false;
    });
    if (!candidates.length) return;
    if (action === 'cancel' && !window.confirm(`Cancel ${candidates.length} visible photo${candidates.length === 1 ? '' : 's'}?`)) return;
    setBusyAction(`${action}:page`);
    setError('');
    try {
      for (const photo of candidates) {
        if (action === 'process') await api.post(`/api/photos/${photo.id}/process-now`);
        if (action === 'cancel') await api.post(`/api/photos/${photo.id}/cancel`);
      }
      await refreshAfterAction();
    } catch (err) {
      setError(getApiErrorMessage(err, 'Bulk action failed.'));
    } finally {
      setBusyAction('');
    }
  };

  return (
    <section className="card photo-ops">
      <div className="photo-ops-header">
        <div>
          <h3>Photo queue</h3>
          <p className="text-xs text-muted">Inspect uploads, processing state, and per-photo controls.</p>
        </div>
        <div className="photo-ops-actions">
          <button className="btn btn-primary btn-sm" onClick={onUploadNow}>
            <Upload size={13} /> Upload now
          </button>
          <button className="btn btn-outline btn-sm" onClick={() => runPageAction('process')} disabled={loading || busyAction === 'process:page'}>
            {busyAction === 'process:page' ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={13} />}
            Process page
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => runPageAction('cancel')} disabled={loading || busyAction === 'cancel:page'}>
            {busyAction === 'cancel:page' ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Ban size={13} />}
            Cancel page
          </button>
          <button className="btn btn-ghost btn-sm" onClick={loadPhotos} disabled={loading}>
            {loading ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={13} />}
            Refresh
          </button>
        </div>
      </div>

      <div className="photo-ops-toolbar">
        <div className="photo-ops-search">
          <Search size={14} />
          <input
            className="input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search filename"
          />
        </div>
        <select className="input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter photos by status">
          {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <select className="input" value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))} aria-label="Rows per page">
          {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size} / page</option>)}
        </select>
      </div>

      {error && <div className="photo-ops-error">{error}</div>}

      <div className="photo-table-wrap">
        <table className="photo-table">
          <thead>
            <tr>
              <th>Preview</th>
              <th>File</th>
              <th>Status</th>
              <th>Faces</th>
              <th>Size</th>
              <th>Uploaded</th>
              <th>Controls</th>
            </tr>
          </thead>
          <tbody>
            {loading && photos.length === 0 ? (
              <tr><td colSpan="7" className="photo-table-empty"><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Loading photos</td></tr>
            ) : photos.length === 0 ? (
              <tr><td colSpan="7" className="photo-table-empty">No photos match this view.</td></tr>
            ) : photos.map((photo) => {
              const processBusy = busyAction === `process:${photo.id}`;
              const cancelBusy = busyAction === `cancel:${photo.id}`;
              const removeBusy = busyAction === `remove:${photo.id}`;
              return (
                <tr key={photo.id}>
                  <td>
                    <button className="photo-thumb-button" onClick={() => setPreview(photo)} disabled={!photo.thumbnail_url && !photo.preview_url}>
                      {photo.thumbnail_url ? <img src={photo.thumbnail_url} alt="" /> : <Eye size={15} />}
                    </button>
                  </td>
                  <td>
                    <div className="photo-file-cell">
                      <span title={photo.filename}>{photo.filename}</span>
                      {photo.error_message && <small title={photo.error_message}>{photo.error_message}</small>}
                    </div>
                  </td>
                  <td><StatusBadge photo={photo} /></td>
                  <td>{Number(photo.face_count || 0)}</td>
                  <td>{formatBytes(photo.original_size_bytes)}</td>
                  <td>{new Date(photo.uploaded_at).toLocaleString()}</td>
                  <td>
                    <div className="photo-row-actions">
                      <button className="btn btn-ghost btn-icon btn-sm" title="Preview" onClick={() => setPreview(photo)} disabled={!photo.thumbnail_url && !photo.preview_url}>
                        <Eye size={13} />
                      </button>
                      <button className="btn btn-ghost btn-icon btn-sm" title="Process now" onClick={() => runRowAction(photo, 'process')} disabled={processBusy || photo.status === 'processing'}>
                        {processBusy ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={13} />}
                      </button>
                      <button className="btn btn-ghost btn-icon btn-sm" title="Cancel" onClick={() => runRowAction(photo, 'cancel')} disabled={cancelBusy || !['queued', 'processing'].includes(photo.status)}>
                        {cancelBusy ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Ban size={13} />}
                      </button>
                      <button className="btn btn-ghost btn-icon btn-sm" title="Remove" onClick={() => runRowAction(photo, 'remove')} disabled={removeBusy}>
                        {removeBusy ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash2 size={13} />}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="photo-ops-footer">
        <span className="text-xs text-muted">Showing {visibleRange} of {total}</span>
        <div className="photo-pagination">
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1 || loading}>
            <ChevronLeft size={13} /> Previous
          </button>
          <span className="text-xs text-muted">Page {page} of {totalPages}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={page >= totalPages || loading}>
            Next <ChevronRight size={13} />
          </button>
        </div>
      </div>

      {preview && (
        <div className="photo-preview-modal" role="dialog" aria-modal="true">
          <div className="photo-preview-panel">
            <div className="photo-preview-header">
              <div>
                <h3>{preview.filename}</h3>
                <p className="text-xs text-muted">{formatBytes(preview.original_size_bytes)} / {preview.face_count || 0} faces</p>
              </div>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setPreview(null)} aria-label="Close preview"><X size={16} /></button>
            </div>
            <div className="photo-preview-body">
              {preview.preview_url || preview.thumbnail_url ? (
                <FaceOverlayImage photo={preview} />
              ) : (
                <div className="photo-table-empty">Preview unavailable</div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
