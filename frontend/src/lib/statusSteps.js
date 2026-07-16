// Human-readable pipeline state shared by the photo table and legacy views.
// New backends expose three simultaneous axes (Drive, R2, and processing) plus
// a computed `stage`. Older status-only rows are inferred conservatively.

export const PIPELINE_STEPS = [
  { key: 'drive_queued', label: 'Drive queued', title: 'Waiting to download from Google Drive' },
  { key: 'drive_downloading', label: 'Drive downloading', title: 'Downloading from Google Drive' },
  { key: 'drive_downloaded', label: 'Drive downloaded', title: 'Downloaded from Google Drive' },
  { key: 'r2_uploading', label: 'Uploading to R2', title: 'Uploading to object storage' },
  { key: 'r2_uploaded', label: 'Uploaded to R2', title: 'Stored in object storage' },
  { key: 'processing_queued', label: 'Processing queued', title: 'Waiting for face processing' },
  { key: 'processing', label: 'Processing', title: 'Detecting and grouping faces' },
  { key: 'processed', label: 'Processed', title: 'Faces detected and grouped' },
];

const STAGE_META = {
  uploading: { label: 'Uploading', cls: 'badge-processing', title: 'Uploading the photo' },
  drive_queued: { label: 'Drive queued', cls: 'badge-queued', title: 'Waiting to download from Google Drive' },
  drive_downloading: { label: 'Drive downloading', cls: 'badge-processing', title: 'Downloading from Google Drive' },
  drive_downloaded: { label: 'Drive downloaded', cls: 'badge-done', title: 'Downloaded from Google Drive' },
  drive_download_failed: { label: 'Drive failed', cls: 'badge-failed', title: 'Google Drive download failed' },
  r2_uploading: { label: 'Uploading to R2', cls: 'badge-processing', title: 'Uploading to object storage' },
  r2_uploaded: { label: 'Uploaded to R2', cls: 'badge-done', title: 'Stored in object storage' },
  r2_upload_failed: { label: 'R2 upload failed', cls: 'badge-failed', title: 'Object storage upload failed' },
  processing_not_started: { label: 'Processing not started', cls: 'badge-inactive', title: 'Face processing has not started' },
  processing_queued: { label: 'Processing queued', cls: 'badge-queued', title: 'Waiting for face processing' },
  processing: { label: 'Processing', cls: 'badge-processing', title: 'Detecting and grouping faces' },
  processed: { label: 'Processed', cls: 'badge-done', title: 'Faces detected and grouped' },
  processing_failed: { label: 'Processing failed', cls: 'badge-failed', title: 'Face processing failed' },
  cancelled: { label: 'Cancelled', cls: 'badge-inactive', title: 'Processing was cancelled' },
};

const AXIS_META = {
  drive: {
    not_applicable: { label: 'N/A', cls: 'badge-inactive', title: 'This photo did not come from Google Drive' },
    not_started: { label: 'Not started', cls: 'badge-inactive', title: 'Drive download has not started' },
    queued: { label: 'Queued', cls: 'badge-queued', title: 'Waiting to download from Google Drive' },
    downloading: { label: 'Downloading', cls: 'badge-processing', title: 'Downloading from Google Drive' },
    downloaded: { label: 'Downloaded', cls: 'badge-done', title: 'Downloaded from Google Drive' },
    failed: { label: 'Failed', cls: 'badge-failed', title: 'Google Drive download failed' },
  },
  r2: {
    not_started: { label: 'Not started', cls: 'badge-inactive', title: 'Object storage upload has not started' },
    queued: { label: 'Queued', cls: 'badge-queued', title: 'Waiting to upload to object storage' },
    uploading: { label: 'Uploading', cls: 'badge-processing', title: 'Uploading to object storage' },
    uploaded: { label: 'Uploaded', cls: 'badge-done', title: 'Stored in object storage' },
    failed: { label: 'Failed', cls: 'badge-failed', title: 'Object storage upload failed' },
  },
  processing: {
    not_started: { label: 'Not started', cls: 'badge-inactive', title: 'Face processing has not started' },
    queued: { label: 'Queued', cls: 'badge-queued', title: 'Waiting for face processing' },
    processing: { label: 'Processing', cls: 'badge-processing', title: 'Detecting and grouping faces' },
    processed: { label: 'Processed', cls: 'badge-done', title: 'Faces detected and grouped' },
    failed: { label: 'Failed', cls: 'badge-failed', title: 'Face processing failed' },
    cancelled: { label: 'Cancelled', cls: 'badge-inactive', title: 'Face processing was cancelled' },
  },
};

function normalize(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function humanize(value) {
  const words = normalize(value).replaceAll('_', ' ');
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : 'Unknown';
}

function stageMeta(value, error) {
  const key = normalize(value);
  const meta = STAGE_META[key] || {
    label: humanize(key),
    cls: 'badge-inactive',
    title: humanize(key),
  };
  return { key, ...meta, title: error || meta.title };
}

function axisMeta(axis, value, error) {
  const key = normalize(value) || 'not_started';
  const meta = AXIS_META[axis]?.[key] || {
    label: humanize(key),
    cls: 'badge-inactive',
    title: humanize(key),
  };
  const failed = key === 'failed';
  return { key, ...meta, title: failed && error ? error : meta.title };
}

function hasStoredFile(photo) {
  return Boolean(photo?.thumbnail_url || photo?.preview_url);
}

function driveStageValue(photo) {
  if (photo?.drive_stage != null) return normalize(photo.drive_stage);
  const ingestion = normalize(photo?.ingestion_stage);
  const fromIngestion = {
    drive_queued: 'queued',
    drive_downloading: 'downloading',
    drive_downloaded: 'downloaded',
    drive_download_failed: 'failed',
  }[ingestion];
  if (fromIngestion) return fromIngestion;

  // Legacy Drive placeholders are the only server rows without a stored file.
  if (!hasStoredFile(photo)) {
    if (photo?.status === 'queued') return 'queued';
    if (photo?.status === 'processing') return 'downloading';
    if (photo?.status === 'failed') return 'failed';
  }
  return 'not_applicable';
}

function r2StageValue(photo, driveStage) {
  if (photo?.r2_stage != null) return normalize(photo.r2_stage);
  const ingestion = normalize(photo?.ingestion_stage);
  const fromIngestion = {
    r2_uploading: 'uploading',
    r2_uploaded: 'uploaded',
    r2_upload_failed: 'failed',
  }[ingestion];
  if (fromIngestion) return fromIngestion;
  if (hasStoredFile(photo)) return 'uploaded';
  if (['queued', 'downloading', 'failed'].includes(driveStage)) return 'not_started';
  return photo?.status === 'failed' ? 'failed' : 'not_started';
}

function processingStageValue(photo) {
  const explicit = normalize(photo?.processing_stage);
  if (explicit) {
    if (explicit === 'processing_queued') return 'queued';
    if (explicit === 'processing_failed') return 'failed';
    return explicit;
  }
  if (!hasStoredFile(photo)) return 'not_started';
  return {
    queued: 'queued',
    processing: 'processing',
    done: 'processed',
    failed: 'failed',
    cancelled: 'cancelled',
  }[photo?.status] || 'not_started';
}

export function photoPipelineStages(photo) {
  const error = photo?.stage_error || photo?.error_message || '';
  const driveValue = driveStageValue(photo);
  const r2Value = r2StageValue(photo, driveValue);
  const processingValue = processingStageValue(photo);
  return {
    drive: axisMeta('drive', driveValue, error),
    r2: axisMeta('r2', r2Value, error),
    processing: axisMeta('processing', processingValue, error),
  };
}

export function photoStage(photo) {
  const error = photo?.stage_error || photo?.error_message || '';
  if (photo?.stage) return stageMeta(photo.stage, error);

  const ingestion = normalize(photo?.ingestion_stage);
  if (ingestion && ingestion !== 'r2_uploaded') return stageMeta(ingestion, error);

  if (!ingestion && photo?.processing_stage == null) {
    const legacyStage = !hasStoredFile(photo)
      ? {
        queued: 'drive_queued',
        processing: 'drive_downloading',
        failed: 'drive_download_failed',
      }[photo?.status]
      : {
        queued: 'processing_queued',
        processing: 'processing',
        done: 'processed',
        failed: 'processing_failed',
      }[photo?.status];
    if (legacyStage) return stageMeta(legacyStage, error);
  }

  const processing = processingStageValue(photo);
  const detailedProcessing = {
    queued: 'processing_queued',
    failed: 'processing_failed',
  }[processing] || processing;
  return stageMeta(detailedProcessing, error);
}
