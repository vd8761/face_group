import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowLeft, Upload, Users, Image, RefreshCw, Merge, Loader2,
  CheckCircle2, AlertCircle, AlertTriangle, Key, Share2, X, Download,
  Search, Pencil, Check
} from 'lucide-react';
import api, { getApiErrorMessage } from '../api/client';
import PhotoUpload from '../components/PhotoUpload';
import PhotoProcessingTable from '../components/PhotoProcessingTable';
import ConfirmActionModal from '../components/ConfirmActionModal';
import ProcessingOverview from '../components/processing/ProcessingOverview';
import { isRunningBatch, useEventProcessing } from '../context/ProcessingContext';

const StatusBadge = ({ status }) => {
  const map = {
    queued:     { cls: 'badge-queued',      label: '⏳ Queued' },
    processing: { cls: 'badge-processing',  label: '⚡ Processing' },
    done:       { cls: 'badge-done',        label: '✅ Done' },
    failed:     { cls: 'badge-failed',      label: '❌ Failed' },
  };
  const { cls, label } = map[status] || map.queued;
  return <span className={`badge ${cls}`}>{label}</span>;
};

export default function EventManager() {
  const { eventId } = useParams();
  const processing = useEventProcessing(eventId);
  const [event, setEvent]     = useState(null);
  const [photos, setPhotos]   = useState([]);
  const [totalServerPhotos, setTotalServerPhotos] = useState(0);
  const [clusters, setClusters] = useState([]);
  const [activeTab, setActiveTab] = useState('upload'); // 'upload' | 'photos' | 'clusters'
  const [loading, setLoading] = useState(true);
  const [reClustering, setReClustering] = useState(false);
  const [merging, setMerging] = useState(false);
  const [mergeIds, setMergeIds] = useState([]);
  const [isMergeMode, setIsMergeMode] = useState(false);
  const [peopleSearch, setPeopleSearch] = useState('');
  const [peopleSort, setPeopleSort] = useState('count');
  const [editingClusterId, setEditingClusterId] = useState(null);
  const [editingLabel, setEditingLabel] = useState('');
  const [renamingClusterId, setRenamingClusterId] = useState(null);
  const [peopleError, setPeopleError] = useState('');
  const hasLiveBatch = processing.batches.some(isRunningBatch);
  
  // Cluster Detail Modal State
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [clusterPhotos, setClusterPhotos] = useState([]);
  const [loadingClusterPhotos, setLoadingClusterPhotos] = useState(false);

  // Deletion Modal State
  const [deleteModal, setDeleteModal] = useState({ isOpen: false, type: null, isDeleting: false });

  const loadEvent = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/events/${eventId}`);
      setEvent(data);
    } catch (e) { console.error(e); }
  }, [eventId]);

  const loadPhotos = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/photos/events/${eventId}?limit=200`);
      setPhotos(data.photos);
      setTotalServerPhotos(data.total || 0);
    } catch (e) { console.error(e); }
  }, [eventId]);

  const loadClusters = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/faces/events/${eventId}/clusters`);
      setClusters(data);
    } catch (e) { console.error(e); }
  }, [eventId]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadEvent(), loadPhotos(), loadClusters()]);
    setLoading(false);
  }, [loadEvent, loadPhotos, loadClusters]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Keep photo rows and People refreshed while the realtime stream reports work.
  useEffect(() => {
    const hasProcessingPhotos = photos.some(p => p.status === 'queued' || p.status === 'processing');
    if (!hasProcessingPhotos && !hasLiveBatch) return;
    const timer = setInterval(() => { loadPhotos(); loadClusters(); loadEvent(); }, 5000);
    return () => clearInterval(timer);
  }, [photos, loadPhotos, loadClusters, loadEvent, hasLiveBatch]);

  const triggerRecluster = async () => {
    setReClustering(true);
    setPeopleError('');
    try {
      await api.post(`/api/faces/events/${eventId}/recluster`);
      setTimeout(() => { loadClusters(); setReClustering(false); }, 3000);
    } catch (error) {
      setPeopleError(getApiErrorMessage(error, 'Could not rebuild People groups.'));
      setReClustering(false);
    }
  };

  const handleDeleteConfirm = async () => {
    setDeleteModal(prev => ({ ...prev, isDeleting: true }));
    try {
      if (deleteModal.type === 'rebuild') {
        const { data } = await api.post(`/api/photos/events/${eventId}/reprocess-faces`);
        setActiveTab('photos');
        setPeopleError('');
        setTimeout(loadAll, 1000);
        alert(data.message || 'Face groups are being rebuilt.');
      } else if (deleteModal.type === 'all') {
        await api.delete(`/api/photos/events/${eventId}/clear?status_filter=all`);
      } else if (deleteModal.type === 'stuck') {
        await api.delete(`/api/photos/events/${eventId}/clear?status_filter=queued`);
        await api.delete(`/api/photos/events/${eventId}/clear?status_filter=failed`);
      }
      loadPhotos(); loadClusters(); loadEvent();
    } catch (e) {
      alert(getApiErrorMessage(e, 'The requested action could not be completed.'));
    } finally {
      setDeleteModal({ isOpen: false, type: null, isDeleting: false });
    }
  };

  const mergeClusters = async () => {
    if (mergeIds.length !== 2) return;
    setMerging(true);
    try {
      await api.post('/api/faces/clusters/merge', { source_cluster_id: mergeIds[0], target_cluster_id: mergeIds[1] });
      setMergeIds([]);
      loadClusters();
    } catch (e) { console.error(e); }
    finally { setMerging(false); }
  };

  const toggleMergeSelect = (id) => {
    setMergeIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 2 ? [...prev, id] : [prev[1], id]);
  };
  
  const handleClusterClick = (cluster) => {
    if (isMergeMode) {
      toggleMergeSelect(cluster.id);
    } else {
      setSelectedCluster(cluster);
      loadClusterPhotos(cluster.id);
    }
  };

  const loadClusterPhotos = async (clusterId) => {
    setLoadingClusterPhotos(true);
    setClusterPhotos([]);
    try {
      const { data } = await api.get(`/api/faces/events/${eventId}/clusters/${clusterId}/photos`);
      setClusterPhotos(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingClusterPhotos(false);
    }
  };

  const renameCluster = async (cluster) => {
    const label = editingLabel.trim();
    setRenamingClusterId(cluster.id);
    setPeopleError('');
    try {
      const { data } = await api.patch(`/api/faces/events/${eventId}/clusters/${cluster.id}`, { label: label || null });
      setClusters(prev => prev.map(item => item.id === cluster.id ? { ...item, ...data, label: data?.label ?? label } : item));
      setSelectedCluster(prev => prev?.id === cluster.id ? { ...prev, ...data, label: data?.label ?? label } : prev);
      setEditingClusterId(null);
      setEditingLabel('');
    } catch (e) {
      setPeopleError(getApiErrorMessage(e, 'Could not rename this person.'));
    } finally {
      setRenamingClusterId(null);
    }
  };

  const copyCode = () => {
    if (event?.access_code) { navigator.clipboard.writeText(event.access_code); }
  };

  if (loading) return (
    <div className="flex justify-center items-center" style={{ minHeight: '60vh' }}>
      <Loader2 size={36} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  const doneCount   = event?.processed_count || photos.filter(p => p.status === 'done').length;
  const failedCount = event?.failed_count != null
    ? Number(event.failed_count) || 0
    : photos.filter(p => p.status === 'failed').length;
  const terminalCount = Math.min(totalServerPhotos, doneCount + failedCount);
  const fallbackFinished = totalServerPhotos > 0 && terminalCount >= totalServerPhotos;
  const visibleClusters = clusters
    .filter((cluster) => {
      const fallbackName = `Person ${cluster.id.slice(0, 6)}`;
      return `${cluster.label || fallbackName}`.toLowerCase().includes(peopleSearch.trim().toLowerCase());
    })
    .sort((a, b) => {
      const aCount = a.photo_count ?? a.member_count ?? 0;
      const bCount = b.photo_count ?? b.member_count ?? 0;
      if (peopleSort === 'name') {
        return (a.label || `Person ${a.id}`).localeCompare(b.label || `Person ${b.id}`);
      }
      if (peopleSort === 'recent') return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
      return bCount - aCount;
    });

  return (
    <div className="page">
      <div className="container">
        {/* Back + header */}
        <div className="flex items-center gap-3 mb-6">
          <Link to="/dashboard" className="btn btn-ghost btn-sm"><ArrowLeft size={15} /></Link>
          <div style={{ flex: 1 }}>
            <h2 style={{ marginBottom: '0.125rem' }}>{event?.name}</h2>
            <p className="text-xs text-muted">{event?.description}</p>
          </div>
          {/* Access code share */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: '0.5rem 1rem' }}>
            <Key size={13} color="var(--accent-light)" />
            <code style={{ fontFamily: 'monospace', fontWeight: 700, color: 'var(--accent-light)', letterSpacing: '0.1em', fontSize: '0.9375rem' }}>{event?.access_code}</code>
            <button className="btn btn-ghost btn-icon btn-sm" onClick={copyCode} title="Copy code"><Share2 size={13} /></button>
          </div>
        </div>

        {/* Quick stats */}
        <div className="grid-4 mb-6" style={{ gap: '0.875rem' }}>
          {[
            { label: 'Total Photos',  value: totalServerPhotos, icon: Image },
            { label: 'Processed',     value: doneCount,         icon: CheckCircle2, color: 'var(--success)' },
            { label: 'Failed',        value: failedCount,       icon: AlertCircle,  color: failedCount > 0 ? 'var(--error)' : undefined },
            { label: 'People',        value: clusters.length,   icon: Users,        color: 'var(--accent-light)' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="stat-card" style={{ padding: '1.125rem' }}>
              <div className="flex items-center gap-2 text-muted mb-1">
                <Icon size={13} color={color} /> <span className="stat-label">{label}</span>
              </div>
              <div className="stat-value" style={{ fontSize: '1.625rem' }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Live processing progress and resources */}
        {processing.hasSnapshot && (
          <div className="mb-6">
            <ProcessingOverview
              title={`${event?.name || 'Event'} processing`}
              subtitle="Image detection, People grouping, throughput and application resources"
              summary={processing.summary}
              resources={processing.resources}
              batches={processing.batches}
              connectionState={processing.connectionState}
              isStale={processing.isStale}
              hasSnapshot={processing.hasSnapshot}
              error={processing.error}
              batchLimit={5}
            />
          </div>
        )}
        {totalServerPhotos > 0 && (!processing.hasSnapshot || processing.batches.length === 0) && (
          <div className="card mb-6" style={{ padding: '1.125rem 1.5rem', background: fallbackFinished ? (failedCount ? 'rgba(245,158,11,0.06)' : 'rgba(16, 185, 129, 0.05)') : undefined, borderColor: fallbackFinished ? (failedCount ? 'rgba(245,158,11,0.24)' : 'rgba(16, 185, 129, 0.2)') : undefined }}>
            <div className="usage-bar-label mb-2">
              <span className="font-semibold text-sm" style={{ color: fallbackFinished ? (failedCount ? '#b45309' : 'var(--success)') : undefined }}>
                {fallbackFinished ? (failedCount ? 'Processing completed with errors' : 'Processing Completed 🎉') : 'Processing Progress'}
              </span>
              <span className="text-sm text-muted">{doneCount} done{failedCount ? ` · ${failedCount} failed` : ''} / {totalServerPhotos}</span>
            </div>
            <div className="progress-bar" style={{ height: 8 }}>
              <div className="progress-bar-fill" style={{ width: `${totalServerPhotos > 0 ? (terminalCount / totalServerPhotos) * 100 : 0}%`, background: fallbackFinished ? (failedCount ? 'var(--warning)' : 'var(--success)') : undefined }} />
            </div>
          </div>
        )}

        {/* Tabs */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--color-border)' }}>
          {[
            { id: 'upload',   label: 'Upload Photos', icon: Upload },
            { id: 'photos',   label: `Photos (${totalServerPhotos})`, icon: Image },
            { id: 'clusters', label: `People (${clusters.length})`, icon: Users },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                padding: '0.625rem 1rem', fontWeight: 700, fontSize: '0.9rem',
                color: activeTab === id ? 'var(--primary)' : 'var(--text-muted)',
                borderBottom: `2px solid ${activeTab === id ? 'var(--primary)' : 'transparent'}`,
                marginBottom: '-1px', display: 'flex', alignItems: 'center', gap: '0.4rem',
                transition: 'all 0.2s ease'
              }}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {/* Upload tab */ }
        <div style={{ display: activeTab === 'upload' ? 'block' : 'none' }}>
          <PhotoUpload eventId={eventId} onUploadComplete={() => { setTimeout(loadAll, 1000); }} />
        </div>

        {/* Photos tab */}
        {activeTab === 'photos' && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <PhotoProcessingTable
              eventId={eventId}
              onChanged={loadAll}
              onUploadNow={() => setActiveTab('upload')}
            />
          </motion.div>
        )}

        {activeTab === '__legacy_photos__' && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="flex justify-between items-center mb-4">
              <span className="text-sm text-muted">
                {totalServerPhotos} total &nbsp;·&nbsp;
                <span style={{ color: 'var(--error)' }}>{failedCount} failed</span>
                &nbsp;·&nbsp;
                <span style={{ color: 'var(--success)' }}>{doneCount} done</span>
              </span>
              <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}>
                {failedCount > 0 && (
                  <button
                    id="retry-failed-btn"
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      const btn = document.getElementById('retry-failed-btn');
                      btn.disabled = true;
                      btn.textContent = 'Retrying…';
                      try {
                        const res = await api.post(`/api/photos/events/${eventId}/retry-failed`);
                        const data = res.data;
                        alert(`✅ ${data.message}\n\nPhotos will process in the background. Refresh the page in 30 seconds.`);
                        setTimeout(() => { loadPhotos(); loadClusters(); }, 3000);
                      } catch(e) {
                        const status = e?.response?.status;
                        if (status === 404) {
                          alert('⏳ Backend is still deploying. Please wait 2-3 minutes and try again.');
                        } else {
                          alert('Error: ' + (e?.response?.data?.detail || e.message));
                        }
                      } finally {
                        btn.disabled = false;
                        btn.textContent = `Retry Failed (${failedCount})`;
                      }
                    }}
                  >
                    <RefreshCw size={13} /> Retry Failed ({failedCount})
                  </button>
                )}
                <button 
                  className="btn btn-outline btn-sm" 
                  onClick={() => setDeleteModal({ isOpen: true, type: 'all', isDeleting: false })}
                >
                  <AlertTriangle size={13} style={{ color: 'var(--error)' }} />
                  Clear All Photos
                </button>
                <button 
                  className="btn btn-outline btn-sm" 
                  onClick={() => setDeleteModal({ isOpen: true, type: 'stuck', isDeleting: false })}
                >
                  <AlertTriangle size={13} style={{ color: 'var(--error)' }} />
                  Clear Stuck
                </button>
                <button className="btn btn-ghost btn-sm" onClick={loadPhotos}>
                  <RefreshCw size={13} /> Refresh
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {photos.slice(0, 100).map((photo) => (
                <div key={photo.id} className="card" style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  {photo.thumbnail_url && (
                    <img src={photo.thumbnail_url} alt={photo.filename} style={{ width: 48, height: 48, borderRadius: '8px', objectFit: 'cover', flexShrink: 0 }} />
                  )}
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div className="text-sm font-medium" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{photo.filename}</div>
                    {photo.error_message && <div className="text-xs" style={{ color: 'var(--error)', marginTop: '2px' }}>{photo.error_message}</div>}
                  </div>
                  <StatusBadge status={photo.status} />
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* People tab */}
        {activeTab === 'clusters' && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="flex justify-between items-center mb-4" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
              <div>
                <span className="text-sm font-semibold">People</span>
                <p className="text-xs text-muted" style={{ margin: '0.15rem 0 0' }}>{clusters.length} people detected across this event</p>
              </div>
              <div className="flex gap-2">
                <button
                  className={`btn btn-sm ${event?.needs_face_rebuild ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setDeleteModal({ isOpen: true, type: 'rebuild', isDeleting: false })}
                  disabled={hasLiveBatch || totalServerPhotos === 0}
                  title={hasLiveBatch ? 'Wait for current processing to finish' : 'Re-run face detection and grouping for every original'}
                >
                  <RefreshCw size={13} />
                  {event?.needs_face_rebuild ? 'Upgrade face groups' : 'Rebuild People'}
                </button>
                <button 
                  className={`btn btn-sm ${isMergeMode ? 'btn-secondary' : 'btn-ghost'}`} 
                  onClick={() => setIsMergeMode(!isMergeMode)}
                >
                  <Merge size={13} />
                  {isMergeMode ? 'Cancel Merge' : 'Merge Mode'}
                </button>
                {isMergeMode && mergeIds.length === 2 && (
                  <button className="btn btn-primary btn-sm" onClick={mergeClusters} disabled={merging}>
                    {merging ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Merge size={13} />}
                    Merge Selected
                  </button>
                )}
                <button className="btn btn-ghost btn-sm" onClick={triggerRecluster} disabled={reClustering || hasLiveBatch}>
                  {reClustering ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={13} />}
                  Re-cluster
                </button>
              </div>
            </div>

            {event?.needs_face_rebuild && (
              <div className="card mb-4" style={{ background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)', padding: '0.85rem 1rem' }}>
                <div style={{ alignItems: 'flex-start', display: 'flex', gap: '0.65rem' }}>
                  <AlertTriangle size={16} color="var(--warning)" style={{ flexShrink: 0, marginTop: 2 }} />
                  <div>
                    <div className="text-sm font-semibold">A newer face model is available</div>
                    <p className="text-xs text-muted" style={{ margin: '0.2rem 0 0' }}>
                      {event.legacy_face_count} legacy face record{event.legacy_face_count === 1 ? '' : 's'} must be reprocessed before they can safely match the new model.
                    </p>
                  </div>
                </div>
              </div>
            )}

            <div className="card mb-4" style={{ alignItems: 'center', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', padding: '0.75rem' }}>
              <div style={{ flex: '1 1 240px', position: 'relative' }}>
                <Search size={14} color="var(--text-muted)" style={{ left: '0.75rem', pointerEvents: 'none', position: 'absolute', top: '50%', transform: 'translateY(-50%)' }} />
                <input
                  className="input"
                  value={peopleSearch}
                  onChange={(event) => setPeopleSearch(event.target.value)}
                  placeholder="Search named or unnamed people"
                  style={{ paddingLeft: '2.25rem' }}
                />
              </div>
              <select className="input" value={peopleSort} onChange={(event) => setPeopleSort(event.target.value)} style={{ flex: '0 0 180px' }} aria-label="Sort people">
                <option value="count">Most photos</option>
                <option value="name">Name</option>
                <option value="recent">Recently updated</option>
              </select>
            </div>

            {peopleError && (
              <div className="card mb-4" style={{ background: 'rgba(239,68,68,0.06)', borderColor: 'rgba(239,68,68,0.2)', color: 'var(--error)', fontSize: '0.8rem', padding: '0.75rem 1rem' }}>
                {peopleError}
              </div>
            )}

            {mergeIds.length > 0 && (
              <div className="card mb-4" style={{ padding: '0.75rem 1rem', background: 'var(--accent-soft)', borderColor: 'rgba(124,58,237,0.3)' }}>
                <p className="text-sm text-accent">
                  {mergeIds.length === 1 ? 'Select one more group to merge.' : 'Two groups selected. Click Merge.'}
                  <button onClick={() => setMergeIds([])} className="btn btn-ghost btn-sm" style={{ marginLeft: '0.75rem', color: 'var(--text-muted)' }}>Cancel</button>
                </p>
              </div>
            )}

            {clusters.length === 0 ? (
              <div className="card text-center" style={{ padding: '3rem' }}>
                <AlertTriangle size={40} color="var(--text-muted)" style={{ margin: '0 auto 1rem' }} />
                <p className="text-secondary">No people yet. Upload photos and let face processing finish first.</p>
              </div>
            ) : visibleClusters.length === 0 ? (
              <div className="card text-center" style={{ padding: '2.5rem' }}>
                <Search size={32} color="var(--text-muted)" style={{ margin: '0 auto 0.75rem' }} />
                <p className="text-secondary">No people match “{peopleSearch}”.</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '1.5rem' }}>
                {visibleClusters.map((cluster) => (
                  <div
                    key={cluster.id}
                    className={`cluster-card ${isMergeMode ? 'merge-mode' : ''}`}
                    style={{ 
                      cursor: 'pointer', 
                      display: 'flex', flexDirection: 'column',
                      outline: mergeIds.includes(cluster.id) ? '3px solid var(--accent-light)' : 'none', 
                      outlineOffset: '2px',
                      borderRadius: 'var(--radius-lg)',
                      opacity: (isMergeMode && mergeIds.length === 2 && !mergeIds.includes(cluster.id)) ? 0.5 : 1
                    }}
                    onClick={() => handleClusterClick(cluster)}
                  >
                    {cluster.sample_thumbnails.length > 0 ? (
                      <div style={{ aspectRatio: '1', borderRadius: 'var(--radius-lg)', overflow: 'hidden', backgroundColor: 'var(--color-surface-2)' }}>
                        <img src={cluster.sample_thumbnails[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      </div>
                    ) : (
                      <div style={{ aspectRatio: '1', borderRadius: 'var(--radius-lg)', background: 'var(--color-surface-3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Users size={32} color="var(--text-muted)" />
                      </div>
                    )}
                    <div style={{ padding: '0.75rem 0.25rem 0', textAlign: 'center' }}>
                      {editingClusterId === cluster.id ? (
                        <form
                          onClick={(event) => event.stopPropagation()}
                          onSubmit={(event) => { event.preventDefault(); renameCluster(cluster); }}
                          style={{ display: 'flex', gap: '0.25rem' }}
                        >
                          <input
                            className="input"
                            value={editingLabel}
                            onChange={(event) => setEditingLabel(event.target.value)}
                            placeholder="Person name"
                            maxLength={200}
                            autoFocus
                            style={{ minWidth: 0, padding: '0.35rem 0.45rem' }}
                          />
                          <button className="btn btn-primary btn-icon btn-sm" type="submit" disabled={renamingClusterId === cluster.id} aria-label="Save person name">
                            {renamingClusterId === cluster.id ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Check size={12} />}
                          </button>
                          <button className="btn btn-ghost btn-icon btn-sm" type="button" onClick={() => setEditingClusterId(null)} aria-label="Cancel rename"><X size={12} /></button>
                        </form>
                      ) : (
                        <div style={{ alignItems: 'center', display: 'flex', gap: '0.25rem', justifyContent: 'center' }}>
                          <div className="text-sm font-semibold truncate" title={cluster.label || `Person ${cluster.id.slice(0, 6)}`}>
                            {cluster.label || `Person ${cluster.id.slice(0, 6)}`}
                          </div>
                          <button
                            className="btn btn-ghost btn-icon btn-sm"
                            onClick={(event) => {
                              event.stopPropagation();
                              setEditingClusterId(cluster.id);
                              setEditingLabel(cluster.label || '');
                              setPeopleError('');
                            }}
                            title="Rename person"
                            aria-label={`Rename ${cluster.label || 'person'}`}
                            style={{ flexShrink: 0, padding: '0.2rem' }}
                          >
                            <Pencil size={11} />
                          </button>
                        </div>
                      )}
                      <div className="text-xs text-muted mt-1">{cluster.photo_count ?? cluster.member_count} photos</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </div>

      {/* Cluster Detail Modal */}
      {selectedCluster && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.8)',
          zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '1rem'
        }}>
          <div style={{
            background: 'var(--color-surface)',
            width: '100%', maxWidth: '800px',
            maxHeight: '90vh', borderRadius: 'var(--radius-lg)',
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
            boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)'
          }}>
            {/* Modal Header */}
            <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div className="flex items-center gap-3">
                <div style={{ width: 48, height: 48, borderRadius: '50%', overflow: 'hidden', border: '2px solid var(--color-border)', flexShrink: 0 }}>
                  {selectedCluster.sample_thumbnails[0] ? (
                    <img src={selectedCluster.sample_thumbnails[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ width: '100%', height: '100%', background: 'var(--color-surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Users size={20} color="var(--text-muted)" />
                    </div>
                  )}
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem' }}>{selectedCluster.label || `Person ${selectedCluster.id.slice(0, 6)}`}</h3>
                  <div className="text-xs text-muted">{selectedCluster.photo_count ?? selectedCluster.member_count} photos for this person</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button 
                  className="btn btn-outline btn-sm"
                  onClick={async () => {
                    const btn = document.getElementById('download-zip-btn');
                    const originalText = btn.innerHTML;
                    btn.innerHTML = '<span style="display:flex;align-items:center;gap:4px">⏳ Downloading...</span>';
                    btn.disabled = true;
                    try {
                      const response = await api.get(`/api/faces/events/${eventId}/clusters/${selectedCluster.id}/download`, { responseType: 'blob' });
                      const url = window.URL.createObjectURL(new Blob([response.data]));
                      const link = document.createElement('a');
                      link.href = url;
                      link.setAttribute('download', `${selectedCluster.label || 'Person_' + selectedCluster.id.slice(0,6)}.zip`);
                      document.body.appendChild(link);
                      link.click();
                      link.parentNode.removeChild(link);
                      window.URL.revokeObjectURL(url);
                    } catch (e) {
                      console.error(e);
                      alert('Failed to download zip. Please try again.');
                    } finally {
                      btn.innerHTML = originalText;
                      btn.disabled = false;
                    }
                  }}
                  id="download-zip-btn"
                >
                  <Download size={14} /> Download ZIP
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setSelectedCluster(null)}>
                  <X size={20} />
                </button>
              </div>
            </div>

            {/* Modal Body */}

            <div style={{ padding: '1.25rem', overflowY: 'auto', flex: 1 }}>
              {loadingClusterPhotos ? (
                <div className="flex justify-center items-center py-8">
                  <Loader2 size={24} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
                </div>
              ) : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                  gap: '1rem'
                }}>
                  {clusterPhotos.map(photo => (
                    <div key={photo.id} style={{
                      aspectRatio: '1', borderRadius: 'var(--radius-md)', overflow: 'hidden',
                      border: '1px solid var(--color-border)', backgroundColor: 'var(--color-surface-2)'
                    }}>
                      {photo.thumbnail_url ? (
                        <img src={photo.thumbnail_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      ) : (
                        <div className="flex items-center justify-center h-full w-full text-muted">
                          <Image size={24} />
                        </div>
                      )}
                    </div>
                  ))}
                  {clusterPhotos.length === 0 && !loadingClusterPhotos && (
                    <div className="text-center text-muted col-span-full py-8">No photos found for this person.</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <ConfirmActionModal
        isOpen={deleteModal.isOpen}
        title={deleteModal.type === 'rebuild' ? 'Rebuild People' : deleteModal.type === 'all' ? "Clear All Photos" : "Clear Stuck Photos"}
        message={
          deleteModal.type === 'rebuild'
            ? 'Every original photo will be reprocessed with the current face model. Existing person names and manual merges will be reset while new groups are built.'
            : deleteModal.type === 'all'
            ? "Are you sure you want to delete ALL photos for this event? This action will permanently remove all photos and face data."
            : "Are you sure you want to delete all queued and failed photos?"
        }
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteModal({ isOpen: false, type: null, isDeleting: false })}
        isLoading={deleteModal.isDeleting}
        confirmText={deleteModal.type === 'rebuild' ? 'Start Rebuild' : 'Delete Photos'}
        destructive={deleteModal.type !== 'rebuild'}
      />
    </div>
  );
}
