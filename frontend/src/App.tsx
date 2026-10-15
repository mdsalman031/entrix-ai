import React, { useEffect, useState } from 'react';
import { getMe, getToken, removeToken } from './api';
import { Layout } from './components/Layout';
import { LoginPage } from './components/LoginPage';
import { TokenResponse, UserInfo } from './types';

export const App: React.FC = () => {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [token, setTokenState] = useState<string | null>(getToken());
  const [initialLoading, setInitialLoading] = useState<boolean>(true);

  const fetchProfile = async () => {
    const currentToken = getToken();
    if (!currentToken) {
      setUser(null);
      setTokenState(null);
      setInitialLoading(false);
      return;
    }

    try {
      const userInfo = await getMe();
      setUser(userInfo);
      setTokenState(currentToken);
    } catch {
      // Token expired or invalid
      removeToken();
      setUser(null);
      setTokenState(null);
    } finally {
      setInitialLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  const handleLogin = (data: TokenResponse) => {
    setTokenState(data.access_token);
    // Optimistically create initial UserInfo, then fetch full profile
    setUser({
      id: data.user_id,
      username: data.username,
      email: `${data.username}@entrix.ai`,
      role: data.role,
      organization_id: data.organization_id,
      organization_name: data.organization_name,
    });
    // Also fetch fresh profile from /auth/me
    getMe()
      .then((info) => setUser(info))
      .catch(() => {
        // Keep optimistic user info if /auth/me fails
      });
  };

  const handleLogout = () => {
    removeToken();
    setTokenState(null);
    setUser(null);
  };

  if (initialLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          fontSize: '14px',
          color: 'var(--text-secondary)',
        }}
      >
        Initializing session...
      </div>
    );
  }

  if (!token || !user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return <Layout user={user} onLogout={handleLogout} />;
};

export default App;
