import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, X, Trash2, Loader2 } from 'lucide-react';

export default function ConfirmActionModal({
  isOpen,
  title,
  message,
  onConfirm,
  onCancel,
  isLoading = false,
  confirmText = "Delete",
  cancelText = "Cancel"
}) {
  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="modal-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.div
          className="modal"
          initial={{ scale: 0.9, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0, y: 20 }}
          transition={{ type: 'spring', stiffness: 300, damping: 25 }}
        >
          <div className="flex items-center gap-3 mb-4">
            <div style={{
              width: 48, height: 48,
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '12px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0
            }}>
              <AlertTriangle size={24} color="var(--error)" />
            </div>
            <div>
              <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>{title}</h3>
              <p className="text-xs text-muted" style={{ margin: 0, marginTop: '4px', lineHeight: 1.5 }}>
                This action cannot be undone.
              </p>
            </div>
          </div>

          <div style={{
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            marginBottom: '1.5rem',
          }}>
            <p className="text-sm" style={{ color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>
              {message}
            </p>
          </div>

          <div className="flex gap-3">
            <button
              onClick={onCancel}
              className="btn btn-ghost w-full"
              disabled={isLoading}
            >
              <X size={16} /> {cancelText}
            </button>
            <button
              onClick={onConfirm}
              className="btn w-full"
              disabled={isLoading}
              style={{
                background: 'var(--error)',
                color: 'white',
                border: 'none',
                opacity: isLoading ? 0.7 : 1
              }}
            >
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> Deleting...
                </>
              ) : (
                <>
                  <Trash2 size={16} /> {confirmText}
                </>
              )}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
