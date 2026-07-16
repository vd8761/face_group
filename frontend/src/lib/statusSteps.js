// Maps a server photo row to a user-facing pipeline step.
//
// Pipeline: select → U: Queued → Uploading → Uploaded · P: Queued →
//           Processing → Processed (or Failed).
//
// Server rows only exist from "P: Queued" onward for local uploads; Google
// Drive imports create placeholder rows before the file reaches storage,
// which is the server-side "U: Queued" state (no thumbnail key yet).
export const PIPELINE_STEPS = [
  { key: 'u_queued', label: 'U: Queued', title: 'Upload is queued' },
  { key: 'uploading', label: 'Uploading', title: 'Uploading to storage' },
  { key: 'p_queued', label: 'Uploaded · P: Queued', title: 'Uploaded — processing queued' },
  { key: 'processing', label: 'Processing', title: 'Detecting faces' },
  { key: 'done', label: 'Processed', title: 'Faces detected and grouped' },
];

export function photoStage(photo) {
  const status = photo?.status;
  if (status === 'failed') {
    return { key: 'failed', label: 'Failed', cls: 'badge-failed', title: photo?.error_message || 'Processing failed' };
  }
  if (status === 'processing') {
    return { key: 'processing', label: 'Processing', cls: 'badge-processing', title: 'Detecting faces' };
  }
  if (status === 'done') {
    return { key: 'done', label: 'Processed', cls: 'badge-done', title: 'Faces detected and grouped' };
  }
  // status === 'queued': storage upload pending (Drive import placeholder) vs
  // stored and waiting for the face pipeline.
  const hasStoredFile = Boolean(photo?.thumbnail_url || photo?.preview_url);
  if (!hasStoredFile) {
    return { key: 'u_queued', label: 'U: Queued', cls: 'badge-queued', title: 'Waiting for the file to reach storage' };
  }
  return { key: 'p_queued', label: 'P: Queued', cls: 'badge-queued', title: 'Uploaded — waiting for face processing' };
}
