export const safeNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const readBatchCount = (batch, field) => {
  const shortName = field.replace(/_images$/, '');
  return safeNumber(batch?.[field] ?? batch?.[shortName]);
};

export function formatRate(value) {
  const rate = safeNumber(value);
  if (rate === 0) return '0';
  if (rate < 10) return rate.toFixed(1);
  return Math.round(rate).toLocaleString();
}

export function formatEta(seconds) {
  if (seconds == null || seconds === '') return 'Calculating…';
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return 'Calculating…';
  if (value < 5) return 'Finishing…';
  if (value < 60) return `${Math.ceil(value)} sec`;
  const minutes = Math.ceil(value / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

export function formatProcessor(processor) {
  const normalized = String(processor || 'pending').toLowerCase();
  if (normalized.includes('mixed')) return 'CPU + GPU';
  if (normalized.includes('cuda') || normalized.includes('gpu')) return 'GPU';
  if (normalized.includes('cpu')) return 'CPU';
  return 'Waiting';
}

export function formatPhase(phase, status) {
  const value = String(phase || status || 'queued').replaceAll('_', ' ');
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function batchProgress(batch) {
  const explicit = Number(batch?.progress_percent);
  if (Number.isFinite(explicit)) return Math.min(100, Math.max(0, explicit));
  const total = readBatchCount(batch, 'total_images');
  const completed = readBatchCount(batch, 'completed_images')
    || readBatchCount(batch, 'succeeded_images')
      + readBatchCount(batch, 'failed_images')
      + readBatchCount(batch, 'skipped_images');
  return total > 0 ? Math.min(100, Math.max(0, (completed / total) * 100)) : 0;
}
