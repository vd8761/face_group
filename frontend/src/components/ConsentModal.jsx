import { motion, AnimatePresence } from 'framer-motion';
import { ShieldAlert, X, Check } from 'lucide-react';

export default function ConsentModal({ eventName, onAccept, onDecline }) {
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
              background: 'rgba(124,58,237,0.15)',
              border: '1px solid rgba(124,58,237,0.3)',
              borderRadius: '12px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0
            }}>
              <ShieldAlert size={24} color="var(--accent-light)" />
            </div>
            <div>
              <h3 style={{ margin: 0 }}>Biometric Consent Required</h3>
              <p className="text-xs text-muted" style={{ margin: 0, marginTop: '2px' }}>
                Event: {eventName}
              </p>
            </div>
          </div>

          <div style={{
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            marginBottom: '1.25rem',
          }}>
            <p className="text-sm" style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
              To find photos you appear in, this app will:
            </p>
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {[
                'Capture or upload a photo of your face (selfie)',
                'Convert your face into a mathematical fingerprint (embedding)',
                'Compare it against faces detected in event photos',
                'Show you photos where you appear',
              ].map((item) => (
                <li key={item} className="flex gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                  <Check size={14} color="var(--success)" style={{ flexShrink: 0, marginTop: 2 }} />
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div style={{
            background: 'rgba(245,158,11,0.08)',
            border: '1px solid rgba(245,158,11,0.2)',
            borderRadius: 'var(--radius-md)',
            padding: '0.875rem',
            marginBottom: '1.5rem',
          }}>
            <p className="text-xs" style={{ color: 'var(--warning)', lineHeight: 1.6 }}>
              ⚠️ Your face data is processed under applicable privacy laws (GDPR / DPDP Act 2023).
              Only your face embedding is stored — not your selfie image.
              You can delete your data at any time from the gallery page.
            </p>
          </div>

          <div className="flex gap-3">
            <button onClick={onDecline} className="btn btn-ghost w-full">
              <X size={16} /> Decline
            </button>
            <button onClick={onAccept} className="btn btn-primary w-full">
              <Check size={16} /> I Consent
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
