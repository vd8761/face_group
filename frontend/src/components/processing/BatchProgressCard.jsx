import { AlertTriangle, CheckCircle2, Clock3, Images, Users } from 'lucide-react';
import DeviceBadge from './DeviceBadge';
import {
  batchProgress,
  formatEta,
  formatPhase,
  formatRate,
  readBatchCount,
  safeNumber,
} from './formatters';

const TERMINAL = new Set(['completed', 'completed_with_errors', 'partial_failed', 'failed', 'cancelled']);

export default function BatchProgressCard({ batch, compact = false }) {
  const total = readBatchCount(batch, 'total_images');
  const succeeded = readBatchCount(batch, 'succeeded_images');
  const failed = readBatchCount(batch, 'failed_images');
  const skipped = readBatchCount(batch, 'skipped_images');
  const active = readBatchCount(batch, 'active_images');
  const completed = readBatchCount(batch, 'completed_images') || succeeded + failed + skipped;
  const percent = batchProgress(batch);
  const isTerminal = TERMINAL.has(batch?.status);
  const hasErrors = failed > 0 || Boolean(batch?.finalization_error) || batch?.status === 'failed' || batch?.status === 'completed_with_errors' || batch?.status === 'partial_failed';
  const StatusIcon = hasErrors ? AlertTriangle : isTerminal ? CheckCircle2 : Clock3;

  return (
    <article className={`batch-progress-card ${compact ? 'compact' : ''}`}>
      <div className="batch-progress-heading">
        <div className="batch-progress-title-wrap">
          <span className={`batch-status-icon ${hasErrors ? 'warning' : isTerminal ? 'success' : 'running'}`}>
            <StatusIcon size={14} />
          </span>
          <div>
            <h4>{batch?.event_name || 'Photo batch'}</h4>
            <p>{formatPhase(batch?.phase, batch?.status)} · {completed.toLocaleString()} of {total.toLocaleString()}</p>
          </div>
        </div>
        <div className="batch-progress-device">
          <DeviceBadge processor={batch?.processor} compact />
          <strong>{Math.round(percent)}%</strong>
        </div>
      </div>

      <progress className={`batch-progress ${hasErrors ? 'has-errors' : ''}`} max="100" value={percent} aria-label={`${batch?.event_name || 'Batch'} progress`} />

      {batch?.finalization_error && (
        <p className="processing-connection-error" style={{ margin: '0.45rem 0 0' }}>
          Grouping retry delayed: {batch.finalization_error}
        </p>
      )}

      {!compact && (
        <div className="batch-progress-metrics">
          <span><Images size={12} /> {active.toLocaleString()} active</span>
          <span><CheckCircle2 size={12} /> {succeeded.toLocaleString()} done</span>
          {failed > 0 && <span className="metric-error"><AlertTriangle size={12} /> {failed.toLocaleString()} failed</span>}
          <span><Users size={12} /> {safeNumber(batch?.faces_detected).toLocaleString()} faces</span>
          <span>{formatRate(batch?.images_per_second)} img/s</span>
          <span>{formatRate(batch?.faces_per_second)} faces/s</span>
          <span><Clock3 size={12} /> {formatEta(batch?.eta_seconds)}</span>
        </div>
      )}
    </article>
  );
}
