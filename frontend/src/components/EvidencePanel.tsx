import React, { useState } from 'react';
import { EvidenceItem, SufficiencyAssessment, SufficiencyDecision } from '../types';

interface EvidencePanelProps {
  evidence: EvidenceItem[];
  sufficiency?: SufficiencyAssessment | null;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({ evidence, sufficiency }) => {
  const [isOpen, setIsOpen] = useState(true);

  if (!evidence.length && !sufficiency) {
    return null;
  }

  const getBadgeClass = (decision?: string) => {
    switch (decision?.toLowerCase()) {
      case SufficiencyDecision.SUFFICIENT:
      case 'sufficient':
        return 'badge badge-sufficient';
      case SufficiencyDecision.INSUFFICIENT:
      case 'insufficient':
        return 'badge badge-insufficient';
      case SufficiencyDecision.RETRY:
      case 'retry':
        return 'badge badge-retry';
      case SufficiencyDecision.ABSTAIN:
      case 'abstain':
        return 'badge badge-abstain';
      default:
        return 'badge badge-abstain';
    }
  };

  return (
    <div className={`evidence-panel ${isOpen ? 'open' : ''}`}>
      <div
        className="evidence-header"
        onClick={() => setIsOpen(!isOpen)}
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsOpen(!isOpen);
          }
        }}
      >
        <div className="evidence-title-group">
          <strong>Authorized Evidence & Sufficiency</strong>
          <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            ({evidence.length} {evidence.length === 1 ? 'chunk' : 'chunks'} retrieved)
          </span>
          {sufficiency && (
            <span className={getBadgeClass(sufficiency.decision)}>
              {sufficiency.decision}
            </span>
          )}
        </div>
        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
          {isOpen ? '▲ Collapse' : '▼ Expand'}
        </span>
      </div>

      {isOpen && (
        <div className="evidence-body">
          {sufficiency && (
            <div className="sufficiency-grid">
              <div className="sufficiency-stat-item">
                <span className="stat-label">Coverage Score</span>
                <span className="stat-value">
                  {(sufficiency.coverage_score * 100).toFixed(0)}%
                </span>
              </div>
              <div className="sufficiency-stat-item">
                <span className="stat-label">Confidence</span>
                <span className="stat-value">
                  {(sufficiency.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {sufficiency.rationale && (
                <div className="sufficiency-stat-item" style={{ gridColumn: '1 / -1' }}>
                  <span className="stat-label">Decision Rationale</span>
                  <span style={{ fontSize: '13px', color: 'var(--text)' }}>
                    {sufficiency.rationale}
                  </span>
                </div>
              )}
            </div>
          )}

          {sufficiency?.missing_information && sufficiency.missing_information.length > 0 && (
            <div className="banner banner-warning" style={{ margin: '12px 0' }}>
              <div>
                <strong>Missing Information:</strong>
                <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                  {sufficiency.missing_information.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {sufficiency?.contradictions && sufficiency.contradictions.length > 0 && (
            <div className="banner banner-error" style={{ margin: '12px 0' }}>
              <div>
                <strong>Contradictions Detected:</strong>
                <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                  {sufficiency.contradictions.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div className="evidence-list">
            {evidence.map((item) => (
              <div key={item.evidence_id || `${item.document_id}-${item.chunk_index}`} className="evidence-card">
                <div className="evidence-card-header">
                  <span className="evidence-card-title">
                    📄 {item.document_title} · Chunk #{item.chunk_index}
                  </span>
                  <span className="evidence-card-score">
                    Score: {typeof item.score === 'number' ? item.score.toFixed(3) : item.score}
                  </span>
                </div>
                <div className="evidence-card-text">{item.text}</div>
                {item.source_id && (
                  <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                    Source: {item.source_id}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
