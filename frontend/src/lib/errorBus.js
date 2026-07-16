// Tiny global error bus: anything in the app can report an error and the
// ErrorCenter component renders them as toasts plus a history drawer.
const listeners = new Set();
let counter = 0;

export function subscribeToErrors(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function reportError(message, context = {}) {
  const entry = {
    id: `err-${Date.now()}-${counter += 1}`,
    message: String(message || 'Unknown error'),
    source: context.source || 'app',        // 'api' | 'runtime' | 'app'
    detail: context.detail || null,          // e.g. "POST /api/photos/… → 500"
    status: context.status ?? null,
    at: new Date().toISOString(),
  };
  listeners.forEach((listener) => {
    try {
      listener(entry);
    } catch {
      // A broken listener must never take down error reporting itself.
    }
  });
  return entry;
}
