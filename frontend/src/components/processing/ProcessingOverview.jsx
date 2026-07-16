import {
  Activity,
  Clock3,
  Gauge,
  Images,
  Radio,
  Server,
  Users,
  WifiOff,
} from 'lucide-react';
import BatchProgressCard from './BatchProgressCard';
import DeviceBadge from './DeviceBadge';
import ResourceMeter from './ResourceMeter';
import { formatEta, formatRate, safeNumber } from './formatters';
import '../../styles/processing.css';

function memoryLabel(used, total) {
  const usedValue = safeNumber(used);
  const totalValue = safeNumber(total);
  if (!totalValue) return null;
  return `${(usedValue / 1024).toFixed(1)} / ${(totalValue / 1024).toFixed(1)} GB memory`;
}

function knownProcessor(value) {
  const normalized = String(value || '').toLowerCase();
  return normalized && normalized !== 'unknown' && normalized !== 'pending' ? value : null;
}

function optionalNumber(value) {
  if (value == null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function slotCount(value) {
  return Math.max(0, Math.round(value)).toLocaleString();
}

function driveScopeLabel(scope) {
  const normalized = String(scope || '').trim().toLowerCase();
  if (normalized === 'global' || normalized === 'globally') return 'globally paced';
  if (normalized === 'worker' || normalized === 'per_worker') return 'paced per worker';
  if (['organization', 'organisation', 'tenant', 'per_organization', 'per_tenant'].includes(normalized)) {
    return 'paced per organization';
  }
  return normalized ? `${normalized.replaceAll('_', ' ')} pacing` : 'paced';
}

export default function ProcessingOverview({
  title = 'Live processing',
  subtitle,
  summary = {},
  resources = {},
  batches = [],
  connectionState = 'connecting',
  isStale = false,
  hasSnapshot = false,
  error,
  showBatches = true,
  batchLimit = 6,
  compact = false,
}) {
  const socketLive = connectionState === 'live';
  const isLive = socketLive && !isStale;
  const connectionLabel = isLive
    ? 'Live'
    : socketLive && isStale
      ? 'Metrics delayed'
      : hasSnapshot
        ? 'Updating periodically'
        : 'Connecting';
  const running = safeNumber(summary.running_batches);
  const remaining = safeNumber(summary.remaining_images);
  const active = safeNumber(summary.active_images);
  const completed = safeNumber(summary.completed_images || summary.succeeded_images);
  const visibleBatches = batches.slice(0, batchLimit);
  const batchProcessors = new Set(
    visibleBatches
      .map((batch) => knownProcessor(batch.processor))
      .filter(Boolean),
  );
  const batchProcessor = batchProcessors.size > 1 ? 'mixed' : [...batchProcessors][0];
  const processor = knownProcessor(resources.processor)
    || knownProcessor(summary.processor)
    || batchProcessor
    || 'pending';
  const processingConcurrency = optionalNumber(resources.processing_concurrency);
  const processingConcurrencyMin = optionalNumber(resources.processing_concurrency_min);
  const processingConcurrencyMax = optionalNumber(resources.processing_concurrency_max)
    ?? processingConcurrency;
  const processingReason = typeof resources.processing_control_reason === 'string'
    ? resources.processing_control_reason.trim()
    : '';
  const driveRate = optionalNumber(resources.drive_downloads_per_minute);
  const hasProcessingControl = processingConcurrency !== null && processingConcurrencyMax !== null;
  const hasDriveRate = driveRate !== null;
  const processingMode = resources.autoscale_enabled === true
    ? 'Adaptive processing'
    : resources.autoscale_enabled === false
      ? 'Fixed processing'
      : 'Processing capacity';
  const processingDetail = [
    processingReason,
    processingConcurrencyMin !== null
      ? `minimum ${slotCount(processingConcurrencyMin)} slot${Math.round(processingConcurrencyMin) === 1 ? '' : 's'}`
      : '',
  ].filter(Boolean).join(' · ');

  return (
    <section className={`processing-overview ${compact ? 'compact' : ''}`} aria-live="polite">
      <div className="processing-overview-header">
        <div>
          <div className="processing-title-line">
            <Activity size={17} />
            <h3>{title}</h3>
            <span className={`live-connection ${isLive ? 'live' : hasSnapshot ? 'fallback' : 'offline'}`}>
              {isLive ? <Radio size={11} /> : <WifiOff size={11} />}
              {connectionLabel}
            </span>
          </div>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <DeviceBadge processor={processor} />
      </div>

      {error && !isLive && <p className="processing-connection-error">{error}</p>}

      <div className="processing-summary-grid">
        <div className="live-metric">
          <Server size={14} />
          <div><strong>{running.toLocaleString()}</strong><span>Running batches</span></div>
        </div>
        <div className="live-metric">
          <Images size={14} />
          <div><strong>{active.toLocaleString()}</strong><span>Images active</span></div>
        </div>
        <div className="live-metric">
          <Gauge size={14} />
          <div><strong>{formatRate(summary.images_per_second)}</strong><span>Images / second</span></div>
        </div>
        <div className="live-metric">
          <Users size={14} />
          <div><strong>{formatRate(summary.faces_per_second)}</strong><span>Faces / second</span></div>
        </div>
        <div className="live-metric">
          <Clock3 size={14} />
          <div><strong>{running ? formatEta(summary.eta_seconds) : '—'}</strong><span>Estimated time</span></div>
        </div>
        <div className="live-metric">
          <Images size={14} />
          <div><strong>{remaining.toLocaleString()}</strong><span>Images remaining</span></div>
        </div>
      </div>

      <div className="resource-grid">
        <ResourceMeter label="Application CPU" value={resources.cpu_percent} detail={`${safeNumber(resources.workers_online)} worker${safeNumber(resources.workers_online) === 1 ? '' : 's'} online`} />
        <ResourceMeter
          label="Application GPU"
          value={resources.gpu_available ? resources.gpu_utilization_percent : 0}
          detail={resources.gpu_available ? memoryLabel(resources.gpu_memory_used_mb, resources.gpu_memory_total_mb) : 'GPU not available'}
          tone="gpu"
        />
      </div>

      {(hasProcessingControl || hasDriveRate) && (
        <div className="processing-operational-status" aria-label="Processing controls">
          {hasProcessingControl && (
            <div className="processing-operational-chip" title={processingDetail || undefined}>
              <Gauge size={13} />
              <strong>
                {processingMode} {slotCount(processingConcurrency)}/{slotCount(processingConcurrencyMax)} slots
              </strong>
              {processingDetail && <span>{processingDetail}</span>}
            </div>
          )}
          {hasDriveRate && (
            <div className="processing-operational-chip drive-rate">
              <Images size={13} />
              <strong>Drive downloads {slotCount(driveRate)}/min</strong>
              <span>{driveScopeLabel(resources.drive_rate_scope)}</span>
            </div>
          )}
        </div>
      )}

      {showBatches && (
        <div className="processing-batches">
          {visibleBatches.length > 0 ? visibleBatches.map((batch) => (
            <BatchProgressCard key={batch.id} batch={batch} compact={compact} />
          )) : (
            <div className="processing-idle">
              <CheckIdleIcon />
              <span>{hasSnapshot
                ? running > 0
                  ? `${running.toLocaleString()} batches are processing across this scope`
                  : `${completed.toLocaleString()} images completed · No batches are running`
                : 'Waiting for processing data…'}</span>
            </div>
          )}
          {batches.length > batchLimit && <p className="more-batches">+{batches.length - batchLimit} more batches</p>}
        </div>
      )}
    </section>
  );
}

function CheckIdleIcon() {
  return <span className="idle-dot" aria-hidden="true" />;
}
