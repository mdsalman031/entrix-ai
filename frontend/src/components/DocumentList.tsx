import React, { useEffect, useState } from 'react';
import { getDocuments, ingestDocument } from '../api';
import { DocumentSummary } from '../types';

export const DocumentList: React.FC = () => {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);

  // Ingest form state
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [roles, setRoles] = useState<string[]>(['viewer', 'editor', 'admin']);
  const [ingesting, setIngesting] = useState(false);
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  const fetchDocuments = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const docs = await getDocuments();
      setDocuments(docs);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setTableError(err.message);
      } else {
        setTableError('Failed to load documents.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  const handleRoleToggle = (role: string) => {
    if (roles.includes(role)) {
      if (roles.length > 1) {
        setRoles(roles.filter((r) => r !== role));
      }
    } else {
      setRoles([...roles, role]);
    }
  };

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) {
      setIngestError('Title and content are required.');
      return;
    }

    setIngesting(true);
    setIngestSuccess(null);
    setIngestError(null);

    try {
      const res = await ingestDocument({
        title: title.trim(),
        content: content.trim(),
        source_id: sourceId.trim() || null,
        allowed_roles: roles,
      });

      setIngestSuccess(
        `Successfully ingested "${res.title}" (${res.chunk_count} ${
          res.chunk_count === 1 ? 'chunk' : 'chunks'
        }). Document ID: ${res.document_id}`
      );
      setTitle('');
      setContent('');
      setSourceId('');

      // Refresh documents table
      await fetchDocuments();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setIngestError(err.message);
      } else {
        setIngestError('Failed to ingest document.');
      }
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Enterprise Knowledge Documents</h1>
        <p className="page-description">
          Manage tenant-isolated documents, index chunks with role-based access control, and
          inspect ingestion metadata.
        </p>
      </div>

      {/* Ingest Form Card */}
      <div className="card">
        <h2 className="card-title">Ingest Document</h2>

        {ingestSuccess && (
          <div className="banner banner-success" role="status">
            <div>{ingestSuccess}</div>
          </div>
        )}

        {ingestError && (
          <div className="banner banner-error" role="alert">
            <div>
              <strong>Ingestion Error:</strong> {ingestError}
            </div>
          </div>
        )}

        <form onSubmit={handleIngest}>
          <div className="form-group">
            <label htmlFor="doc-title" className="form-label">
              Document Title *
            </label>
            <input
              id="doc-title"
              type="text"
              className="form-input"
              placeholder="e.g. Q3 Security Compliance Policy"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              disabled={ingesting}
            />
          </div>

          <div className="form-group">
            <label htmlFor="doc-content" className="form-label">
              Document Content *
            </label>
            <textarea
              id="doc-content"
              className="form-textarea"
              rows={6}
              placeholder="Paste raw text, policies, architecture documentation..."
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              disabled={ingesting}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label htmlFor="doc-source-id" className="form-label">
                Source ID / Link (Optional)
              </label>
              <input
                id="doc-source-id"
                type="text"
                className="form-input"
                placeholder="e.g. s3://acme-bucket/policy.pdf or KB-892"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                disabled={ingesting}
              />
            </div>

            <div className="form-group">
              <label className="form-label">Permitted Roles (RBAC)</label>
              <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
                {(['viewer', 'editor', 'admin'] as const).map((r) => (
                  <label
                    key={r}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '13px',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={roles.includes(r)}
                      onChange={() => handleRoleToggle(r)}
                      disabled={ingesting}
                    />
                    <span style={{ textTransform: 'capitalize' }}>{r}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={ingesting}
            style={{ marginTop: '8px' }}
          >
            {ingesting ? (
              <>
                <span className="spinner" aria-hidden="true" />
                <span>Processing & Indexing...</span>
              </>
            ) : (
              'Ingest Document'
            )}
          </button>
        </form>
      </div>

      {/* Documents List Card */}
      <div className="card">
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '14px',
          }}
        >
          <h2 className="card-title" style={{ margin: 0 }}>
            Permitted Documents ({documents.length})
          </h2>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={fetchDocuments}
            disabled={loading}
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {tableError && (
          <div className="banner banner-error" role="alert">
            <div>
              <strong>Error:</strong> {tableError}
            </div>
          </div>
        )}

        {loading && !documents.length ? (
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>Loading documents...</p>
        ) : documents.length === 0 ? (
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
            No documents found for your tenant and role. Use the ingest form above to add one.
          </p>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Title</th>
                  <th>Source</th>
                  <th>Version</th>
                  <th>Chunks</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      <code style={{ fontSize: '12px' }}>{doc.id.substring(0, 8)}...</code>
                    </td>
                    <td>
                      <strong>{doc.title}</strong>
                    </td>
                    <td style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                      {doc.source_id || '—'}
                    </td>
                    <td>v{doc.version}</td>
                    <td>
                      <span className="badge badge-proposed">{doc.chunk_count} chunks</span>
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {new Date(doc.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
