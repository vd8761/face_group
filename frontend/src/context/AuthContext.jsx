import { createContext, useContext, useState, useCallback } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const stored = localStorage.getItem('pg_user');
      return stored ? JSON.parse(stored) : null;
    } catch { return null; }
  });

  const login = useCallback(async (email, password) => {
    const { data } = await api.post('/api/auth/login', { email, password });
    localStorage.setItem('pg_token', data.access_token);
    localStorage.setItem('pg_user', JSON.stringify(data));
    setUser(data);
    return data;
  }, []);

  const attendeeJoin = useCallback(async (accessCode, email, password, fullName) => {
    const { data } = await api.post('/api/auth/attendee-join', {
      access_code: accessCode,
      email,
      password,
      full_name: fullName,
    });
    localStorage.setItem('pg_token', data.access_token);
    localStorage.setItem('pg_user', JSON.stringify(data));
    setUser(data);
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('pg_token');
    localStorage.removeItem('pg_user');
    setUser(null);
  }, []);

  const isRole = useCallback((...roles) => {
    return roles.includes(user?.role);
  }, [user]);

  return (
    <AuthContext.Provider value={{ user, login, attendeeJoin, logout, isRole }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
