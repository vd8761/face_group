import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowLeft, Upload, Users, Image, RefreshCw, Merge, Loader2,
  CheckCircle2, AlertCircle, Clock, AlertTriangle, Key, Share2, X
} from 'lucide-react';
import api from '../api/client';
import PhotoUpload from '../components/PhotoUpload';

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
  const [event, setEvent]     = useState(null);
  const [photos, setPhotos]   = useState([]);
  const [clusters, setClusters] = useState([]);
  const [activeTab, setActiveTab] = useState('upload'); // 'upload' | 'photos' | 'clusters'
  const [loading, setLoading] = useState(true);
  const [reClustering, setReClustering] = useState(false);
  const [merging, setMerging] = useState(false);
  const [mergeIds, setMergeIds] = useState([]);
  const [isMergeMode, setIsMergeMode] = useState(false);
  
  // Cluster Detail Modal State
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [clusterPhotos, setClusterPhotos] = useState([]);
  const [loadingClusterPhotos, setLoadingClusterPhotos] = useState(false);

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

  // Poll photos every 5s while any are processing
  useEffect(() => {
    const processing = photos.some(p => p.status === 'queued' || p.status === 'processing');
    if (!processing) return;
    const timer = setInterval(() => { loadPhotos(); loadClusters(); loadEvent(); }, 5000);
    return () => clearInterval(timer);
  }, [photos, loadPhotos, loadClusters, loadEvent]);

  const triggerRecluster = async () => {
    setReClustering(true);
    try {
      await api.post(`/api/faces/events/${eventId}/recluster`);
      setTimeout(() => { loadClusters(); setReClustering(false); }, 3000);
    } catch (e) { setReClustering(false); }
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

  const copyCode = () => {
    if (event?.access_code) { navigator.clipboard.writeText(event.access_code); }
  };

  if (loading) return (
    <div className="flex justify-center items-center" style={{ minHeight: '60vh' }}>
      <Loader2 size={36} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  const doneCount   = photos.filter(p => p.status === 'done').length;
  const failedCount = photos.filter(p => p.status === 'failed').length;

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
            { label: 'Total Photos',  value: photos.length,    icon: Image },
            { label: 'Processed',     value: doneCount,         icon: CheckCircle2, color: 'var(--success)' },
            { label: 'Failed',        value: failedCount,       icon: AlertCircle,  color: failedCount > 0 ? 'var(--error)' : undefined },
            { label: 'Face Groups',   value: clusters.length,   icon: Users,        color: 'var(--accent-light)' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="stat-card" style={{ padding: '1.125rem' }}>
              <div className="flex items-center gap-2 text-muted mb-1">
                <Icon size={13} color={color} /> <span className="stat-label">{label}</span>
              </div>
              <div className="stat-value" style={{ fontSize: '1.625rem' }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Processing progress bar */}
        {photos.length > 0 && (
          <div className="card mb-6" style={{ padding: '1.125rem 1.5rem' }}>
            <div className="usage-bar-label mb-2">
              <span className="font-semibold text-sm">Processing Progress</span>
              <span className="text-sm text-muted">{doneCount} / {photos.length} photos done</span>
            </div>
            <div className="progress-bar" style={{ height: 8 }}>
              <div className="progress-bar-fill" style={{ width: `${photos.length > 0 ? (doneCount / photos.length) * 100 : 0}%` }} />
            </div>
          </div>
        )}

        {/* Tabs */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--color-border)' }}>
          {[
            { id: 'upload',   label: 'Upload Photos', icon: Upload },
            { id: 'photos',   label: `Photos (${photos.length})`, icon: Image },
            { id: 'clusters', label: `Face Groups (${clusters.length})`, icon: Users },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                padding: '0.625rem 1rem', fontWeight: 600, fontSize: '0.875rem',
                color: activeTab === id ? 'var(--accent-light)' : 'var(--text-muted)',
                borderBottom: `2px solid ${activeTab === id ? 'var(--accent-light)' : 'transparent'}`,
                marginBottom: '-1px', display: 'flex', alignItems: 'center', gap: '0.4rem',
              }}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {/* Upload tab — always mounted so switching tabs doesn't cancel ongoing uploads */}
        <div style={{ display: activeTab === 'upload' ? 'block' : 'none' }}>
          <PhotoUpload eventId={eventId} onUploadComplete={() => { setTimeout(loadAll, 1000); }} />
        </div>

        {/* Photos tab */}
        {activeTab === 'photos' && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="flex justify-between items-center mb-4">
              <span className="text-sm text-muted">{photos.length} total photos</span>
              <div className="flex items-center gap-2">
                <button 
                  className="btn btn-outline btn-sm" 
                  onClick={async () => {
                    if (window.confirm("Delete all queued and failed photos?")) {
                      await api.delete(`/api/photos/events/${eventId}/clear?status_filter=queued`);
                      await api.delete(`/api/photos/events/${eventId}/clear?status_filter=failed`);
                      loadPhotos(); loadClusters(); loadEvent();
                    }
                  }}
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

        {/* Clusters / Face groups tab */}
        {activeTab === 'clusters' && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="flex justify-between items-center mb-4" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
              <span className="text-sm text-muted">{clusters.length} face groups detected</span>
              <div className="flex gap-2">
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
                <button className="btn btn-ghost btn-sm" onClick={triggerRecluster} disabled={reClustering}>
                  {reClustering ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={13} />}
                  Re-cluster
                </button>
              </div>
            </div>

            {mergeIds.length > 0 && (
              <div className="card mb-4" style={{ padding: '0.75rem 1rem', background: 'var(--accent-soft)', borderColor: 'rgba(124,58,237,0.3)' }}>
                <p className="text-sm text-accent">
                  {mergeIds.length === 1 ? 'Select one more group to merge.' : 'Two groups selected — click Merge.'}
                  <button onClick={() => setMergeIds([])} className="btn btn-ghost btn-sm" style={{ marginLeft: '0.75rem', color: 'var(--text-muted)' }}>Cancel</button>
                </p>
              </div>
            )}

            {clusters.length === 0 ? (
              <div className="card text-center" style={{ padding: '3rem' }}>
                <AlertTriangle size={40} color="var(--text-muted)" style={{ margin: '0 auto 1rem' }} />
                <p className="text-secondary">No face groups yet — upload and process photos first.</p>
              </div>
            ) : (
              <div className="grid-3" style={{ gap: '1rem' }}>
                {clusters.map((cluster) => (
                  <div
                    key={cluster.id}
                    className={`cluster-card ${isMergeMode ? 'merge-mode' : ''}`}
                    style={{ 
                      cursor: 'pointer', 
                      outline: mergeIds.includes(cluster.id) ? '2px solid var(--accent-light)' : 'none', 
                      outlineOffset: '2px',
                      opacity: (isMergeMode && mergeIds.length === 2 && !mergeIds.includes(cluster.id)) ? 0.5 : 1
                    }}
                    onClick={() => handleClusterClick(cluster)}
                  >
                    {cluster.sample_thumbnails.length > 0 ? (
                      <div className="cluster-faces">
                        {[...Array(3)].map((_, i) => (
                          <img key={i} src={cluster.sample_thumbnails[i] || cluster.sample_thumbnails[0]} alt="" style={{ width: '100%', aspectRatio: '1', objectFit: 'cover' }} />
                        ))}
                      </div>
                    ) : (
                      <div style={{ height: 100, background: 'var(--color-surface-3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Users size={32} color="var(--text-muted)" />
                      </div>
                    )}
                    <div style={{ padding: '0.875rem' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold">{cluster.label || `Person ${cluster.id.slice(0, 6)}`}</span>
                        <span className="badge badge-active">{cluster.member_count} photos</span>
                      </div>
                      {mergeIds.includes(cluster.id) && (
                        <div className="text-xs text-accent mt-1">✓ Selected for merge</div>
                      )}
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
                <div style={{ width: 40, height: 40, borderRadius: '50%', overflow: 'hidden' }}>
                  <img src={selectedCluster.sample_thumbnails[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem' }}>{selectedCluster.label || `Person ${selectedCluster.id.slice(0, 6)}`}</h3>
                  <div className="text-xs text-muted">{selectedCluster.member_count} photos</div>
                </div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelectedCluster(null)}>
                <X size={20} />
              </button>
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
    </div>
  );
}
