import React, { useState } from 'react';
import { UserInfo } from '../types';
import { ActionPanel } from './ActionPanel';
import { Chat } from './Chat';
import { DocumentList } from './DocumentList';

interface LayoutProps {
  user: UserInfo | null;
  onLogout: () => void;
}

type TabType = 'chat' | 'documents' | 'actions';

export const Layout: React.FC<LayoutProps> = ({ user, onLogout }) => {
  const [activeTab, setActiveTab] = useState<TabType>('chat');

  return (
    <div className="app-container">
      {/* Header bar */}
      <header className="header" role="banner">
        <div className="header-brand">
          <span className="brand-title">Entrix AI</span>
          <span className="brand-subtitle">Enterprise RAG & Autonomous Agent Platform</span>
        </div>

        <div className="header-actions">
          {user && (
            <div className="user-badge" aria-label="Current authenticated user">
              <span className="user-name">
                {user.username} ({user.role})
              </span>
              <span className="user-meta">{user.organization_name}</span>
            </div>
          )}

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onLogout}
            title="Log out of session"
          >
            Sign Out
          </button>
        </div>
      </header>

      {/* Main layout with sidebar and content */}
      <div className="main-layout">
        <aside className="sidebar" aria-label="Platform navigation">
          <button
            type="button"
            className={`sidebar-nav-item ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
            aria-current={activeTab === 'chat' ? 'page' : undefined}
          >
            <span aria-hidden="true">💬</span>
            <span>Knowledge Chat</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeTab === 'documents' ? 'active' : ''}`}
            onClick={() => setActiveTab('documents')}
            aria-current={activeTab === 'documents' ? 'page' : undefined}
          >
            <span aria-hidden="true">📄</span>
            <span>Documents & Ingest</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeTab === 'actions' ? 'active' : ''}`}
            onClick={() => setActiveTab('actions')}
            aria-current={activeTab === 'actions' ? 'page' : undefined}
          >
            <span aria-hidden="true">⚡</span>
            <span>Agentic Actions</span>
          </button>
        </aside>

        <main className="content-area" role="main">
          {activeTab === 'chat' && <Chat />}
          {activeTab === 'documents' && <DocumentList />}
          {activeTab === 'actions' && <ActionPanel />}
        </main>
      </div>
    </div>
  );
};
