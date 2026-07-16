import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Shield, Building2, Plus, Trash2, Power,
  Users, Image, HardDrive, Search, X, Loader2,
  FileText, Activity
} from 'lucide-react';
import api from '../api/client';
import { isRunningBatch, useProcessing } from '../context/ProcessingContext';
import ProcessingOverview from '../components/processing/ProcessingOverview';

const PLAN_OPTIONS = ['starter', 'pro', 'enterprise'];
const PLAN_COLORS  = { starter: 'var(--text-muted)', pro: 'var(--accent-light)', enterprise: 'var(--accent2)' };

export default function SuperAdminPanel() {
  const processing = useProcessing();
  const [stats, setStats]   = useState(null);
  const [tenants, setTenants] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: '', organizer_email: '', organizer_password: '', organizer_name: '', plan: 'starter',
  });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [tab, setTab] = useState('orgs'); // 'orgs' | 'logs'

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, tRes, lRes] = await Promise.all([
        api.get('/api/admin/stats'),
        api.get('/api/admin/tenants?limit=100'),
        api.get('/api/admin/audit-logs?page_size=50'),
      ]);
      setStats(sRes.data);
      setTenants(tRes.data);
      setAuditLogs(lRes.data.logs);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const createTenant = async () => {
    setCreating(true); setCreateError('');
    try {
      await api.post('/api/admin/tenants', createForm);
      setShowCreate(false);
      setCreateForm({ name: '', organizer_email: '', organizer_password: '', organizer_name: '', plan: 'starter' });
      loadData();
    } catch (e) { setCreateError(e.response?.data?.detail || 'Creation failed'); }
    finally { setCreating(false); }
  };

  const toggleActive = async (tenant) => {
    await api.patch(`/api/admin/tenants/${tenant.id}`, { is_active: !tenant.is_active });
    loadData();
  };

  const changePlan = async (tenantId, plan) => {
    await api.patch(`/api/admin/tenants/${tenantId}/subscription`, { plan });
    loadData();
  };

  const deleteTenant = async (tenantId) => {
    if (!confirm('Delete this organization and ALL its data? This cannot be undone.')) return;
    await api.delete(`/api/admin/tenants/${tenantId}`);
    loadData();
  };

  const filtered = tenants.filter(t =>
    t.name.toLowerCase().includes(search.toLowerCase()) ||
    t.slug.toLowerCase().includes(search.toLowerCase())
  );

  const fmtBytes = (b) => {
    if (!b) return '0 B';
    if (b > 1e9) return `${(b/1e9).toFixed(2)} GB`;
    if (b > 1e6) return `${(b/1e6).toFixed(1)} MB`;
    return `${(b/1024).toFixed(0)} KB`;
  };

  const platformBatches = [...processing.batches].sort((a, b) => {
    const activeDifference = Number(isRunningBatch(b)) - Number(isRunningBatch(a));
    if (activeDifference) return activeDifference;
    return new Date(b.updated_at || b.started_at || 0) - new Date(a.updated_at || a.started_at || 0);
  });

  return (
    <div className="page">
      <div className="container">
        {/* Header */}
        <div className="flex items-center justify-between mb-8" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div className="flex items-center gap-3">
            <div style={{ width: 44, height: 44, background: 'linear-gradient(135deg,var(--accent),var(--accent-light))', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Shield size={22} color="#fff" />
            </div>
            <div>
              <h2 style={{ margin: 0 }}>Super Admin</h2>
              <p className="text-xs text-muted" style={{ margin: 0 }}>Platform control center</p>
            </div>
          </div>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={16} /> New Organization
          </button>
        </div>

        {/* Stats row */}
        {stats && (
          <div className="grid-4 mb-8" style={{ gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            {[
              { icon: Building2, label: 'Total Orgs',   value: stats.total_tenants,   sub: `${stats.active_tenants} active` },
              { icon: Users,     label: 'Events',        value: stats.total_events },
              { icon: Image,     label: 'Photos',        value: stats.total_photos.toLocaleString() },
              { icon: HardDrive, label: 'Storage Used',  value: fmtBytes(stats.total_storage_bytes) },
              { icon: Activity,  label: 'Processing Queue', value: processing.hasSnapshot ? processing.summary.remaining_images.toLocaleString() : stats.processing_queue_depth, sub: processing.hasSnapshot ? `${processing.summary.running_batches} batches running` : 'Queued and active' },
            ].map(({ icon: Icon, label, value, sub }) => (
              <div key={label} className="stat-card">
                <div className="flex items-center gap-2 text-muted mb-1">
                  <Icon size={14} />
                  <span className="stat-label">{label}</span>
                </div>
                <div className="stat-value">{value}</div>
                {sub && <p className="text-xs text-muted" style={{ margin: 0 }}>{sub}</p>}
              </div>
            ))}
          </div>
        )}

        <div className="mb-8">
          <ProcessingOverview
            title="Platform processing"
            subtitle="Totals across all organizations and active processing workers"
            summary={processing.summary}
            resources={processing.resources}
            batches={platformBatches}
            connectionState={processing.connectionState}
            isStale={processing.isStale}
            hasSnapshot={processing.hasSnapshot}
            error={processing.error}
            batchLimit={8}
          />
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--color-border)', paddingBottom: '0' }}>
          {[{ id: 'orgs', label: 'Organizations', icon: Building2 }, { id: 'logs', label: 'Audit Logs', icon: FileText }].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                padding: '0.625rem 1rem', fontWeight: 600, fontSize: '0.875rem',
                color: tab === id ? 'var(--accent-light)' : 'var(--text-muted)',
                borderBottom: `2px solid ${tab === id ? 'var(--accent-light)' : 'transparent'}`,
                marginBottom: '-1px', display: 'flex', alignItems: 'center', gap: '0.4rem',
              }}
            >
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {tab === 'orgs' && (
          <>
            {/* Search */}
            <div style={{ position: 'relative', maxWidth: 360, marginBottom: '1.25rem' }}>
              <Search size={15} color="var(--text-muted)" style={{ position: 'absolute', left: '0.875rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
              <input className="input" placeholder="Search organizations…" value={search} onChange={e => setSearch(e.target.value)} style={{ paddingLeft: '2.5rem' }} />
            </div>

            {loading ? (
              <div className="flex justify-center" style={{ padding: '4rem' }}>
                <Loader2 size={32} color="var(--accent-light)" style={{ animation: 'spin 1s linear infinite' }} />
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
                {filtered.map((tenant) => {
                  const tenantRunningBatches = platformBatches.filter(
                    (batch) => String(batch.tenant_id || batch.organization_id || '') === String(tenant.id) && isRunningBatch(batch),
                  );
                  return (
                  <motion.div
                    key={tenant.id}
                    className="card"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    style={{ padding: '1.25rem 1.5rem' }}
                  >
                    <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
                      <div className="flex items-center gap-3">
                        <div style={{ width: 40, height: 40, background: 'var(--accent-soft)', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          <Building2 size={18} color="var(--accent-light)" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span style={{ fontWeight: 700 }}>{tenant.name}</span>
                            <span className={`badge ${tenant.is_active ? 'badge-active' : 'badge-failed'}`}>
                              {tenant.is_active ? 'Active' : 'Suspended'}
                            </span>
                            {tenantRunningBatches.length > 0 && (
                              <span className="badge badge-processing">{tenantRunningBatches.length} processing</span>
                            )}
                          </div>
                          <div className="text-xs text-muted">{tenant.slug} · {tenant.event_count} events · {tenant.photo_count} photos · {tenant.storage_used_gb} GB</div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2" style={{ flexWrap: 'wrap' }}>
                        {/* Plan selector */}
                        <select
                          value={tenant.subscription?.plan || 'starter'}
                          onChange={e => changePlan(tenant.id, e.target.value)}
                          style={{
                            background: 'var(--color-surface-2)', border: '1px solid var(--color-border)',
                            borderRadius: 'var(--radius-md)', padding: '0.375rem 0.75rem',
                            color: PLAN_COLORS[tenant.subscription?.plan] || 'var(--text-muted)',
                            fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
                          }}
                        >
                          {PLAN_OPTIONS.map(p => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
                        </select>

                        <button className="btn btn-ghost btn-sm" onClick={() => toggleActive(tenant)} title={tenant.is_active ? 'Suspend' : 'Activate'}>
                          <Power size={14} />
                        </button>
                        <button className="btn btn-danger btn-sm" onClick={() => deleteTenant(tenant.id)} title="Delete organization">
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>

                    {/* Subscription usage bar */}
                    {tenant.subscription && (
                      <div style={{ marginTop: '1rem' }}>
                        <div className="usage-bar-label">
                          <span>Storage: {tenant.storage_used_gb} GB / {tenant.subscription.max_storage_gb} GB</span>
                          <span>{Math.min(100, Math.round((tenant.storage_used_gb / tenant.subscription.max_storage_gb) * 100))}%</span>
                        </div>
                        <div className="progress-bar" style={{ marginTop: '0.375rem' }}>
                          <div className="progress-bar-fill" style={{ width: `${Math.min(100, (tenant.storage_used_gb / tenant.subscription.max_storage_gb) * 100)}%` }} />
                        </div>
                      </div>
                    )}
                  </motion.div>
                  );
                })}
                {filtered.length === 0 && (
                  <div className="text-center" style={{ padding: '3rem', color: 'var(--text-muted)' }}>No organizations found</div>
                )}
              </div>
            )}
          </>
        )}

        {tab === 'logs' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {auditLogs.map((log) => (
              <div key={log.id} className="card" style={{ padding: '0.875rem 1.25rem', display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <span className="badge badge-active" style={{ fontFamily: 'monospace', fontSize: '0.7rem' }}>{log.action}</span>
                <span className="text-xs text-muted">{log.resource_type} {log.resource_id ? `#${log.resource_id.slice(0, 8)}` : ''}</span>
                <span className="text-xs text-muted" style={{ marginLeft: 'auto' }}>{new Date(log.created_at).toLocaleString()}</span>
                {log.ip_address && <span className="text-xs text-muted">{log.ip_address}</span>}
              </div>
            ))}
            {auditLogs.length === 0 && <div className="text-center" style={{ padding: '3rem', color: 'var(--text-muted)' }}>No audit logs yet</div>}
          </div>
        )}
      </div>

      {/* Create org modal */}
      <AnimatePresence>
        {showCreate && (
          <motion.div className="modal-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div className="modal" initial={{ scale: 0.93, y: 16 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.93, y: 16 }}>
              <div className="flex items-center justify-between mb-6">
                <h3>Create Organization</h3>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}><X size={16} /></button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {createError && <div style={{ color: 'var(--error)', fontSize: '0.875rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', padding: '0.75rem' }}>{createError}</div>}
                {[
                  { key: 'name',               label: 'Organization Name',    type: 'text',     placeholder: 'Acme Events' },
                  { key: 'organizer_name',      label: 'Organizer Name',       type: 'text',     placeholder: 'John Doe' },
                  { key: 'organizer_email',     label: 'Organizer Email',      type: 'email',    placeholder: 'john@acme.com' },
                  { key: 'organizer_password',  label: 'Temporary Password',   type: 'password', placeholder: '••••••••' },
                ].map(({ key, label, type, placeholder }) => (
                  <div key={key} className="input-group">
                    <label className="input-label">{label}</label>
                    <input className="input" type={type} placeholder={placeholder} value={createForm[key]} onChange={e => setCreateForm(p => ({ ...p, [key]: e.target.value }))} />
                  </div>
                ))}
                <div className="input-group">
                  <label className="input-label">Subscription Plan</label>
                  <select className="input" value={createForm.plan} onChange={e => setCreateForm(p => ({ ...p, plan: e.target.value }))}>
                    {PLAN_OPTIONS.map(p => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
                  </select>
                </div>
                <div className="flex gap-3 mt-2">
                  <button className="btn btn-ghost w-full" onClick={() => setShowCreate(false)}>Cancel</button>
                  <button className="btn btn-primary w-full" onClick={createTenant} disabled={creating}>
                    {creating ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> : <Plus size={15} />}
                    Create
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
