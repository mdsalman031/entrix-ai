import React, { useState } from 'react';
import { login, setToken } from '../api';
import { TokenResponse } from '../types';

interface LoginPageProps {
  onLogin: (data: TokenResponse) => void;
}

interface DemoUser {
  username: string;
  role: string;
  org: string;
  defaultPassword?: string;
}

const DEMO_USERS: Record<string, DemoUser[]> = {
  'Org A — Acme Corp': [
    { username: 'alice', role: 'admin', org: 'Acme Corp', defaultPassword: 'password' },
    { username: 'bob', role: 'editor', org: 'Acme Corp', defaultPassword: 'password' },
    { username: 'charlie', role: 'viewer', org: 'Acme Corp', defaultPassword: 'password' },
  ],
  'Org B — Globex Inc': [
    { username: 'diana', role: 'admin', org: 'Globex Inc', defaultPassword: 'password' },
    { username: 'eve', role: 'editor', org: 'Globex Inc', defaultPassword: 'password' },
  ],
};

export const LoginPage: React.FC<LoginPageProps> = ({ onLogin }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('Please provide both username and password.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const data = await login({ username: username.trim(), password });
      setToken(data.access_token);
      onLogin(data);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Login failed. Please check your credentials and server status.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleQuickSelect = (user: DemoUser) => {
    setUsername(user.username);
    setPassword(user.defaultPassword || 'password');
    setError(null);
  };

  return (
    <div className="login-wrapper">
      <div className="login-card">
        <header className="login-header">
          <h1 className="login-logo">Entrix AI</h1>
          <p className="login-subtitle">Enterprise RAG & Autonomous Agent Platform</p>
        </header>

        <div className="dev-notice" role="note">
          <strong>Notice:</strong> This is a DEVELOPMENT authentication endpoint intended for
          testing and demonstrations. Production deployments integrate with SAML/OIDC SSO.
        </div>

        {error && (
          <div className="banner banner-error" role="alert">
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="form-group">
            <label htmlFor="login-username" className="form-label">
              Username
            </label>
            <input
              id="login-username"
              type="text"
              className="form-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. alice"
              autoComplete="username"
              required
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="login-password" className="form-label">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
              disabled={loading}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', marginTop: '8px' }}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                <span>Authenticating...</span>
              </>
            ) : (
              'Sign In'
            )}
          </button>
        </form>

        <section className="quick-select-section" aria-labelledby="quick-select-heading">
          <h2 id="quick-select-heading" className="quick-select-title">
            Demo Identity Quick-Select
          </h2>
          {Object.entries(DEMO_USERS).map(([orgGroup, users]) => (
            <div key={orgGroup} className="quick-select-group">
              <div className="quick-select-org-label">{orgGroup}</div>
              <div className="quick-select-buttons">
                {users.map((u) => (
                  <button
                    key={u.username}
                    type="button"
                    className="btn-pill"
                    onClick={() => handleQuickSelect(u)}
                    title={`Fill ${u.username} (${u.role})`}
                  >
                    {u.username} <span style={{ opacity: 0.65 }}>({u.role})</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
};
