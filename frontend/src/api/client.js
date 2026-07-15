import axios from 'axios';

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 5 minutes, needed for large batch photo uploads
});

export function getWebSocketUrl(path = '/api/processing/ws') {
  const base = new URL(API_BASE_URL, window.location.origin);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = path.startsWith('/') ? path : `/${path}`;
  base.search = '';
  base.hash = '';
  return base.toString();
}

export function getApiErrorMessage(error, fallback = 'Something went wrong') {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (!item || typeof item !== 'object') return null;
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== 'body').join('.')
          : '';
        const message = item.msg || item.message;
        return message ? `${location ? `${location}: ` : ''}${message}` : null;
      })
      .filter(Boolean);
    if (messages.length) return messages.join(' · ');
  }
  if (detail && typeof detail === 'object') {
    const message = detail.message || detail.msg;
    if (typeof message === 'string' && message.trim()) return message;
  }
  if (typeof error?.message === 'string' && error.message.trim()) return error.message;
  return fallback;
}

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('pg_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401, clear token and redirect to login
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('pg_token');
      localStorage.removeItem('pg_user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
