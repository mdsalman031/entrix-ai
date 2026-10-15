import React, { useState } from 'react';
import { submitQuery } from '../api';
import { QueryResponse } from '../types';
import { EvidencePanel } from './EvidencePanel';

export const Chat: React.FC = () => {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState<number>(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<QueryResponse | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await submitQuery({
        query: query.trim(),
        top_k: Number(topK) || 5,
      });
      setResponse(res);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to process query. Please verify backend connection.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="page-header">
        <h1 className="page-title">Enterprise Knowledge Retrieval & RAG</h1>
        <p className="page-description">
          Ask questions grounded strictly in authorized enterprise documents with sufficiency
          guarantees.
        </p>
      </div>

      <div className="card">
        <form onSubmit={handleSubmit} className="query-form">
          <div className="form-group">
            <label htmlFor="query-input" className="form-label">
              Query
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                id="query-input"
                type="text"
                className="form-input"
                placeholder="Ask about policies, internal guides, system architecture..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                disabled={loading}
                autoFocus
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={loading || !query.trim()}
                style={{ minWidth: '110px' }}
              >
                {loading ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    <span>Searching...</span>
                  </>
                ) : (
                  'Query RAG'
                )}
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label htmlFor="top-k-select" style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Top K Chunks:
              </label>
              <select
                id="top-k-select"
                className="form-select"
                style={{ width: '80px', padding: '4px 8px', fontSize: '13px' }}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                disabled={loading}
              >
                <option value={3}>3</option>
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={15}>15</option>
              </select>
            </div>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Fail-closed authorization: candidate chunks outside your tenant/role are discarded.
            </span>
          </div>
        </form>
      </div>

      {error && (
        <div className="banner banner-error" role="alert">
          <div>
            <strong>Error:</strong> {error}
          </div>
        </div>
      )}

      {response && (
        <>
          {/* Abstention Banner */}
          {response.abstained && (
            <div className="banner banner-warning" role="alert">
              <div>
                <strong>Answer Withheld (Sufficiency Controller): </strong>
                {response.abstention_reason ||
                  'The retrieved authorized evidence did not satisfy the factual sufficiency threshold. To prevent hallucination, the system abstains from answering.'}
              </div>
            </div>
          )}

          {/* Answer Card */}
          {response.answer && (
            <div className="answer-card">
              <div className="answer-header">
                <strong>Grounded Response</strong>
                <div style={{ display: 'flex', gap: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                  <span>Latency: {response.latency_ms.toFixed(0)} ms</span>
                  <span>
                    Retry: {response.retry_attempted ? 'Attempted' : 'None'}
                  </span>
                </div>
              </div>

              <div className="answer-body">{response.answer}</div>

              {/* Citations */}
              {response.citations && response.citations.length > 0 && (
                <div className="citations-section">
                  <div className="citations-title">Grounded Citations</div>
                  {response.citations.map((c, idx) => (
                    <div key={idx} className="citation-item">
                      <div className="citation-header">
                        [{idx + 1}] {c.document_title} (Chunk #{c.chunk_index})
                        {c.source_id && ` · Source: ${c.source_id}`}
                      </div>
                      {c.excerpt && <div className="citation-excerpt">"{c.excerpt}"</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Evidence and Sufficiency Panel */}
          <EvidencePanel evidence={response.evidence} sufficiency={response.sufficiency} />
        </>
      )}
    </div>
  );
};
