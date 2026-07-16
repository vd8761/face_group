import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertOctagon, AlertTriangle, Bell, Trash2, X } from 'lucide-react';
import { subscribeToErrors, reportError } from '../lib/errorBus';

const TOAST_LIFETIME_MS = 9000;
const MAX_TOASTS = 4;
const MAX_HISTORY = 100;
const DEDUPE_WINDOW_MS = 4000;

function shortTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return '';
  }
}

export default function ErrorCenter() {
  const [toasts, setToasts] = useState([]);
  const [history, setHistory] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const timersRef = useRef(new Map());
  const lastEntryRef = useRef({ message: '', at: 0 });

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const pushEntry = useCallback((entry) => {
    lastEntryRef.current = { message: entry.message, at: Date.now() };
    setHistory((prev) => [entry, ...prev].slice(0, MAX_HISTORY));
    setUnseen((prev) => prev + 1);

    setToasts((prev) => {
      // A visible toast with the same message absorbs the repeat: bump its
      // counter and extend its lifetime instead of stacking duplicates.
      const existing = prev.find((toast) => toast.message === entry.message);
      if (existing) {
        const timer = timersRef.current.get(existing.id);
        if (timer) clearTimeout(timer);
        timersRef.current.set(
          existing.id,
          setTimeout(() => dismissToast(existing.id), TOAST_LIFETIME_MS),
        );
        return prev.map((toast) => (
          toast.id === existing.id
            ? { ...toast, count: (toast.count || 1) + 1, at: entry.at, detail: entry.detail || toast.detail }
            : toast
        ));
      }
      const timer = setTimeout(() => dismissToast(entry.id), TOAST_LIFETIME_MS);
      timersRef.current.set(entry.id, timer);
      return [{ ...entry, count: 1 }, ...prev].slice(0, MAX_TOASTS);
    });
  }, [dismissToast]);

  useEffect(() => subscribeToErrors(pushEntry), [pushEntry]);

  // Runtime errors and unhandled promise rejections surface here too.
  useEffect(() => {
    const onError = (event) => {
      // Ignore cross-origin "Script error." noise with no useful detail.
      if (event?.message === 'Script error.' && !event?.filename) return;
      reportError(event?.message || 'Unexpected script error', {
        source: 'runtime',
        detail: event?.filename ? `${event.filename}:${event.lineno || 0}` : null,
      });
    };
    const onRejection = (event) => {
      const reason = event?.reason;
      // Axios errors are already reported by the API interceptor.
      if (reason?.isAxiosError || reason?.config?.url) return;
      const message = reason?.message || (typeof reason === 'string' ? reason : 'Unhandled promise rejection');
      reportError(message, { source: 'runtime' });
    };
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  useEffect(() => () => {
    timersRef.current.forEach((timer) => clearTimeout(timer));
    timersRef.current.clear();
  }, []);

  const openDrawer = () => { setDrawerOpen(true); setUnseen(0); };

  return (
    <>
      {/* ── Toast stack ── */}
      <div className="error-toast-stack" role="region" aria-label="Error notifications">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 40 }}
              className="error-toast"
              role="alert"
            >
              <AlertOctagon size={16} className="error-toast-icon" />
              <div className="error-toast-body">
                <div className="error-toast-message">
                  {toast.message}
                  {toast.count > 1 && <span className="error-toast-count">×{toast.count}</span>}
                </div>
                {toast.detail && <div className="error-toast-detail">{toast.detail}</div>}
              </div>
              <button
                className="error-toast-close"
                onClick={() => dismissToast(toast.id)}
                aria-label="Dismiss error"
              >
                <X size={13} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* ── Floating error-log button (only when there is history) ── */}
      {history.length > 0 && !drawerOpen && (
        <button className="error-center-fab" onClick={openDrawer} title="Show error log">
          <Bell size={15} />
          {unseen > 0 && <span className="error-center-fab-badge">{unseen > 99 ? '99+' : unseen}</span>}
        </button>
      )}

      {/* ── History drawer ── */}
      <AnimatePresence>
        {drawerOpen && (
          <motion.aside
            initial={{ x: 360 }}
            animate={{ x: 0 }}
            exit={{ x: 360 }}
            transition={{ type: 'tween', duration: 0.2 }}
            className="error-center-drawer"
            aria-label="Error log"
          >
            <div className="error-center-drawer-header">
              <span><AlertTriangle size={14} /> Error log ({history.length})</span>
              <div style={{ display: 'flex', gap: '0.35rem' }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setHistory([])} title="Clear log">
                  <Trash2 size={13} />
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => setDrawerOpen(false)} aria-label="Close error log">
                  <X size={14} />
                </button>
              </div>
            </div>
            <div className="error-center-drawer-list">
              {history.length === 0 && <div className="error-center-empty">No errors recorded.</div>}
              {history.map((entry) => (
                <div key={entry.id} className="error-center-item">
                  <div className="error-center-item-top">
                    <span className={`error-center-source error-center-source-${entry.source}`}>{entry.source}</span>
                    <span className="error-center-time">{shortTime(entry.at)}</span>
                  </div>
                  <div className="error-center-item-message">{entry.message}</div>
                  {entry.detail && <div className="error-center-item-detail">{entry.detail}</div>}
                </div>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
