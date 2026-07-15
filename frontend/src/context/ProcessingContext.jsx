import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import api, { getWebSocketUrl } from '../api/client';
import { useAuth } from './AuthContext';

const ProcessingContext = createContext(null);

const EMPTY_SUMMARY = {
  running_batches: 0,
  total_images: 0,
  completed_images: 0,
  succeeded_images: 0,
  failed_images: 0,
  skipped_images: 0,
  active_images: 0,
  remaining_images: 0,
  faces_detected: 0,
  images_per_second: 0,
  faces_per_second: 0,
  eta_seconds: null,
};

const EMPTY_RESOURCES = {
  processor: 'pending',
  cpu_percent: 0,
  gpu_available: false,
  gpu_utilization_percent: 0,
  gpu_memory_used_mb: 0,
  gpu_memory_total_mb: 0,
  workers_online: 0,
  stale: true,
  sampled_at: null,
};

const TERMINAL_BATCH_STATUSES = new Set([
  'completed',
  'completed_with_errors',
  'partial_failed',
  'failed',
  'cancelled',
]);

const numberValue = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const batchCount = (batch, field) => {
  const shortName = field.replace(/_images$/, '');
  return numberValue(batch?.[field] ?? batch?.[shortName]);
};

export function isRunningBatch(batch) {
  return Boolean(batch?.status) && !TERMINAL_BATCH_STATUSES.has(batch.status);
}

export function summarizeBatches(batches = []) {
  const summary = { ...EMPTY_SUMMARY };
  const processors = new Set();

  batches.forEach((batch) => {
    if (isRunningBatch(batch)) summary.running_batches += 1;
    summary.total_images += batchCount(batch, 'total_images');
    summary.completed_images += batchCount(batch, 'completed_images');
    summary.succeeded_images += batchCount(batch, 'succeeded_images');
    summary.failed_images += batchCount(batch, 'failed_images');
    summary.skipped_images += batchCount(batch, 'skipped_images');
    summary.active_images += batchCount(batch, 'active_images');
    summary.remaining_images += batchCount(batch, 'remaining_images');
    summary.faces_detected += numberValue(batch?.faces_detected);
    summary.images_per_second += numberValue(batch?.images_per_second);
    summary.faces_per_second += numberValue(batch?.faces_per_second);
    if (isRunningBatch(batch) && batch?.processor) processors.add(batch.processor);
  });

  if (!summary.completed_images) {
    summary.completed_images = summary.succeeded_images + summary.failed_images + summary.skipped_images;
  }

  if (!summary.remaining_images) {
    summary.remaining_images = Math.max(0, summary.total_images - summary.completed_images);
  }

  summary.eta_seconds = summary.images_per_second > 0
    ? Math.ceil(summary.remaining_images / summary.images_per_second)
    : batches.reduce((max, batch) => Math.max(max, numberValue(batch?.eta_seconds)), 0) || null;
  summary.processor = processors.size > 1 ? 'mixed' : [...processors][0] || 'pending';
  return summary;
}

function unwrapMessage(message) {
  if (message?.data && typeof message.data === 'object' && !Array.isArray(message.data)) {
    return { ...message, ...message.data };
  }
  return message || {};
}

function normalizeResources(resources) {
  if (!resources || Object.keys(resources).length === 0) return {};
  const gpuPercent = resources.gpu_utilization_percent ?? resources.gpu_percent;
  const memoryUsedMb = resources.gpu_memory_used_mb
    ?? (resources.gpu_memory_used_bytes != null ? Number(resources.gpu_memory_used_bytes) / 1024 / 1024 : 0);
  const memoryTotalMb = resources.gpu_memory_total_mb
    ?? (resources.gpu_memory_total_bytes != null ? Number(resources.gpu_memory_total_bytes) / 1024 / 1024 : 0);
  return {
    ...resources,
    gpu_available: resources.gpu_available ?? gpuPercent != null,
    gpu_utilization_percent: gpuPercent ?? 0,
    gpu_memory_used_mb: memoryUsedMb,
    gpu_memory_total_mb: memoryTotalMb,
    workers_online: resources.workers_online ?? resources.worker_count ?? 0,
  };
}

export function ProcessingProvider({ children }) {
  const { user } = useAuth();
  const enabled = user?.role === 'organizer' || user?.role === 'super_admin';
  const [snapshot, setSnapshot] = useState({
    scope: null,
    summary: EMPTY_SUMMARY,
    resources: EMPTY_RESOURCES,
    batches: [],
    seq: 0,
    emitted_at: null,
  });
  const [connectionState, setConnectionState] = useState(enabled ? 'connecting' : 'idle');
  const [hasSnapshot, setHasSnapshot] = useState(false);
  const [transportStale, setTransportStale] = useState(false);
  const [error, setError] = useState(null);
  const lastMessageAtRef = useRef(0);

  const applySnapshot = useCallback((rawMessage) => {
    const message = unwrapMessage(rawMessage);
    setSnapshot((previous) => ({
      scope: message.scope ?? previous.scope,
      summary: { ...EMPTY_SUMMARY, ...previous.summary, ...(message.summary || {}) },
      resources: { ...EMPTY_RESOURCES, ...previous.resources, ...normalizeResources(message.resources) },
      batches: Array.isArray(message.batches) ? message.batches : previous.batches,
      seq: message.seq ?? previous.seq,
      emitted_at: message.emitted_at ?? new Date().toISOString(),
    }));
    lastMessageAtRef.current = Date.now();
    setHasSnapshot(true);
    setTransportStale(false);
    setError(null);
  }, []);

  const applyIncrementalMessage = useCallback((rawMessage) => {
    const message = unwrapMessage(rawMessage);
    if (message.type === 'processing.snapshot' || message.summary || Array.isArray(message.batches)) {
      applySnapshot(message);
      return;
    }

    if (message.type === 'system.metrics' && message.resources) {
      setSnapshot((previous) => ({
        ...previous,
        resources: { ...previous.resources, ...normalizeResources(message.resources) },
        emitted_at: message.emitted_at ?? previous.emitted_at,
        seq: message.seq ?? previous.seq,
      }));
      lastMessageAtRef.current = Date.now();
      setTransportStale(false);
      return;
    }

    const incomingBatch = message.batch || (
      message.type?.startsWith('batch.') && message.id ? message : null
    );
    if (incomingBatch) {
      setSnapshot((previous) => {
        const index = previous.batches.findIndex((batch) => batch.id === incomingBatch.id);
        const batches = [...previous.batches];
        if (index >= 0) batches[index] = { ...batches[index], ...incomingBatch };
        else batches.unshift(incomingBatch);
        return {
          ...previous,
          batches,
          summary: message.summary
            ? { ...previous.summary, ...message.summary }
            : summarizeBatches(batches),
          emitted_at: message.emitted_at ?? previous.emitted_at,
          seq: message.seq ?? previous.seq,
        };
      });
      lastMessageAtRef.current = Date.now();
      setTransportStale(false);
    }
  }, [applySnapshot]);

  const refresh = useCallback(async () => {
    if (!enabled) return false;
    try {
      const { data } = await api.get('/api/processing/snapshot', { timeout: 15000 });
      applySnapshot(data);
      return true;
    } catch (requestError) {
      if (requestError?.response?.status !== 404) {
        setError(requestError?.response?.data?.detail || requestError.message || 'Live metrics unavailable');
      }
      return false;
    }
  }, [applySnapshot, enabled]);

  useEffect(() => {
    if (!enabled) {
      setConnectionState('idle');
      setHasSnapshot(false);
      setSnapshot({
        scope: null,
        summary: EMPTY_SUMMARY,
        resources: EMPTY_RESOURCES,
        batches: [],
        seq: 0,
        emitted_at: null,
      });
      return undefined;
    }

    let disposed = false;
    let socket = null;
    let reconnectTimer = null;
    let fallbackTimer = null;
    let reconnectAttempt = 0;
    const token = user?.access_token || localStorage.getItem('pg_token');

    const stopFallback = () => {
      if (fallbackTimer) clearInterval(fallbackTimer);
      fallbackTimer = null;
    };

    const startFallback = () => {
      if (fallbackTimer || disposed) return;
      refresh();
      fallbackTimer = setInterval(refresh, 15000);
    };

    const scheduleReconnect = () => {
      if (disposed || reconnectTimer) return;
      reconnectAttempt += 1;
      const baseDelay = Math.min(30000, 1000 * (2 ** Math.min(reconnectAttempt - 1, 5)));
      const delay = baseDelay + Math.round(Math.random() * 500);
      setConnectionState('reconnecting');
      startFallback();
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed || !token) return;
      setConnectionState(reconnectAttempt ? 'reconnecting' : 'connecting');
      try {
        socket = new WebSocket(getWebSocketUrl('/api/processing/ws'));
      } catch (socketError) {
        setError(socketError.message || 'Could not open live connection');
        scheduleReconnect();
        return;
      }
      const openedSocket = socket;

      openedSocket.onopen = () => {
        if (disposed || socket !== openedSocket) return;
        openedSocket.send(JSON.stringify({ type: 'auth', token }));
      };

      openedSocket.onmessage = (event) => {
        if (disposed || socket !== openedSocket) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'error' || message.type === 'processing.error') {
            setError(message.detail || message.message || 'Live processing connection failed');
            return;
          }
          applyIncrementalMessage(message);
          reconnectAttempt = 0;
          setConnectionState('live');
          stopFallback();
        } catch {
          setError('Received an invalid live processing update');
        }
      };

      openedSocket.onerror = () => {
        if (!disposed && socket === openedSocket) setError('Live connection interrupted; using periodic updates');
      };

      openedSocket.onclose = () => {
        if (socket !== openedSocket) return;
        socket = null;
        scheduleReconnect();
      };
    };

    refresh();
    connect();

    const staleTimer = setInterval(() => {
      if (lastMessageAtRef.current && Date.now() - lastMessageAtRef.current > 20000) {
        setTransportStale(true);
        setError('Live updates stalled; using periodic updates while reconnecting.');
        startFallback();
        setConnectionState('reconnecting');
        if (socket && (
          socket.readyState === WebSocket.OPEN
          || socket.readyState === WebSocket.CONNECTING
        )) {
          socket.close(4000, 'Processing stream stale');
        } else {
          scheduleReconnect();
        }
      }
    }, 5000);

    return () => {
      disposed = true;
      clearInterval(staleTimer);
      stopFallback();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.close(1000, 'Component disposed');
      }
    };
  }, [applyIncrementalMessage, enabled, refresh, user?.access_token]);

  const value = useMemo(() => ({
    ...snapshot,
    hasSnapshot,
    connectionState,
    isStale: transportStale || Boolean(snapshot.resources?.stale),
    error,
    refresh,
  }), [connectionState, error, hasSnapshot, refresh, snapshot, transportStale]);

  return <ProcessingContext.Provider value={value}>{children}</ProcessingContext.Provider>;
}

export function useProcessing() {
  const context = useContext(ProcessingContext);
  if (!context) throw new Error('useProcessing must be used inside ProcessingProvider');
  return context;
}

export function useEventProcessing(eventId) {
  const processing = useProcessing();
  const batches = useMemo(
    () => processing.batches.filter((batch) => String(batch.event_id) === String(eventId)),
    [eventId, processing.batches],
  );
  const summary = useMemo(() => summarizeBatches(batches), [batches]);
  return { ...processing, batches, summary };
}
