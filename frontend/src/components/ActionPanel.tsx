import React, { useEffect, useState } from 'react';
import { executeAction, getActionHistory } from '../api';
import { ActionHistoryItem, ActionResponse, ActionStatus } from '../types';

type SupportedAction = 'create_task' | 'get_task_status' | 'update_task';

export const ActionPanel: React.FC = () => {
  const [selectedAction, setSelectedAction] = useState<SupportedAction>('create_task');

  // Form states
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState('medium');
  const [assignee, setAssignee] = useState('');
  const [taskId, setTaskId] = useState('');
  const [taskStatus, setTaskStatus] = useState('in_progress');
  const [notes, setNotes] = useState('');

  // Execution states
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<ActionResponse | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);

  // History states
  const [history, setHistory] = useState<ActionHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const loadHistory = async () => {
    setLoadingHistory(true);
    try {
      const data = await getActionHistory();
      setHistory(data);
    } catch {
      // Ignore or silence non-critical history error
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  const handleExecute = async (e: React.FormEvent) => {
    e.preventDefault();
    setExecuting(true);
    setExecutionError(null);
    setExecutionResult(null);

    let parameters: Record<string, unknown> = {};

    if (selectedAction === 'create_task') {
      if (!title.trim()) {
        setExecutionError('Task title is required.');
        setExecuting(false);
        return;
      }
      parameters = {
        title: title.trim(),
        description: description.trim(),
        priority,
        assignee: assignee.trim(),
      };
    } else if (selectedAction === 'get_task_status') {
      if (!taskId.trim()) {
        setExecutionError('Task ID is required.');
        setExecuting(false);
        return;
      }
      parameters = { task_id: taskId.trim() };
    } else if (selectedAction === 'update_task') {
      if (!taskId.trim()) {
        setExecutionError('Task ID is required.');
        setExecuting(false);
        return;
      }
      parameters = {
        task_id: taskId.trim(),
        status: taskStatus,
        notes: notes.trim(),
      };
    }

    try {
      const result = await executeAction({
        action_name: selectedAction,
        parameters,
      });
      setExecutionResult(result);
      // Reload action history
      await loadHistory();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setExecutionError(err.message);
      } else {
        setExecutionError('Failed to execute action.');
      }
    } finally {
      setExecuting(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const s = status.toLowerCase();
    let badgeClass = 'badge-abstain';
    if (s === ActionStatus.EXECUTED || s === 'executed') {
      badgeClass = 'badge-executed';
    } else if (s === ActionStatus.AUTHORIZED || s === 'authorized') {
      badgeClass = 'badge-authorized';
    } else if (s === ActionStatus.PROPOSED || s === 'proposed') {
      badgeClass = 'badge-proposed';
    } else if (s === ActionStatus.REJECTED || s === 'rejected' || s === ActionStatus.FAILED || s === 'failed') {
      badgeClass = 'badge-rejected';
    }
    return <span className={`badge ${badgeClass}`}>{status}</span>;
  };

  // Render status pipeline display
  const renderStatusPipeline = (status: string) => {
    const s = status.toLowerCase();
    const isRejected = s === 'rejected' || s === 'failed';

    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '12px 16px',
          backgroundColor: '#f9fafb',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          marginBottom: '16px',
        }}
      >
        <span style={{ fontSize: '13px', fontWeight: 600 }}>Workflow:</span>
        <span
          className={`badge ${
            s === 'proposed' || s === 'authorized' || s === 'executed'
              ? 'badge-proposed'
              : 'badge-abstain'
          }`}
        >
          Proposed
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>→</span>
        <span
          className={`badge ${
            s === 'authorized' || s === 'executed' ? 'badge-authorized' : 'badge-abstain'
          }`}
        >
          Authorized
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>→</span>
        {isRejected ? (
          <span className="badge badge-rejected">{s}</span>
        ) : (
          <span className={`badge ${s === 'executed' ? 'badge-executed' : 'badge-abstain'}`}>
            Executed
          </span>
        )}
      </div>
    );
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Agentic Actions & Policy Control</h1>
        <p className="page-description">
          Execute external side-effects governed by fine-grained authorization policies and audit
          logging.
        </p>
      </div>

      <div className="card">
        <h2 className="card-title">Execute Action</h2>

        <form onSubmit={handleExecute}>
          <div className="form-group">
            <label htmlFor="action-select" className="form-label">
              Select Action
            </label>
            <select
              id="action-select"
              className="form-select"
              value={selectedAction}
              onChange={(e) => {
                setSelectedAction(e.target.value as SupportedAction);
                setExecutionResult(null);
                setExecutionError(null);
              }}
              disabled={executing}
            >
              <option value="create_task">create_task (Create Task in System)</option>
              <option value="get_task_status">get_task_status (Query Task State)</option>
              <option value="update_task">update_task (Update Task Status)</option>
            </select>
          </div>

          {/* Dynamic Parameters */}
          {selectedAction === 'create_task' && (
            <>
              <div className="form-group">
                <label htmlFor="task-title" className="form-label">
                  Title *
                </label>
                <input
                  id="task-title"
                  type="text"
                  className="form-input"
                  placeholder="e.g. Upgrade PostgreSQL staging cluster"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  disabled={executing}
                />
              </div>

              <div className="form-group">
                <label htmlFor="task-desc" className="form-label">
                  Description
                </label>
                <textarea
                  id="task-desc"
                  className="form-textarea"
                  placeholder="Task details and deliverables..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  disabled={executing}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label htmlFor="task-priority" className="form-label">
                    Priority
                  </label>
                  <select
                    id="task-priority"
                    className="form-select"
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    disabled={executing}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="task-assignee" className="form-label">
                    Assignee
                  </label>
                  <input
                    id="task-assignee"
                    type="text"
                    className="form-input"
                    placeholder="e.g. dev-ops-team"
                    value={assignee}
                    onChange={(e) => setAssignee(e.target.value)}
                    disabled={executing}
                  />
                </div>
              </div>
            </>
          )}

          {selectedAction === 'get_task_status' && (
            <div className="form-group">
              <label htmlFor="status-task-id" className="form-label">
                Task ID *
              </label>
              <input
                id="status-task-id"
                type="text"
                className="form-input"
                placeholder="e.g. TASK-1024 or UUID"
                value={taskId}
                onChange={(e) => setTaskId(e.target.value)}
                required
                disabled={executing}
              />
            </div>
          )}

          {selectedAction === 'update_task' && (
            <>
              <div className="form-group">
                <label htmlFor="update-task-id" className="form-label">
                  Task ID *
                </label>
                <input
                  id="update-task-id"
                  type="text"
                  className="form-input"
                  placeholder="e.g. TASK-1024"
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  required
                  disabled={executing}
                />
              </div>

              <div className="form-group">
                <label htmlFor="update-task-status" className="form-label">
                  New Status
                </label>
                <select
                  id="update-task-status"
                  className="form-select"
                  value={taskStatus}
                  onChange={(e) => setTaskStatus(e.target.value)}
                  disabled={executing}
                >
                  <option value="pending">Pending</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="update-task-notes" className="form-label">
                  Notes
                </label>
                <input
                  id="update-task-notes"
                  type="text"
                  className="form-input"
                  placeholder="Reason or update summary..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  disabled={executing}
                />
              </div>
            </>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={executing}
            style={{ marginTop: '8px' }}
          >
            {executing ? (
              <>
                <span className="spinner" aria-hidden="true" />
                <span>Authorizing & Executing...</span>
              </>
            ) : (
              'Execute Action'
            )}
          </button>
        </form>

        {/* Execution Feedback */}
        {executionError && (
          <div className="banner banner-error" style={{ marginTop: '16px' }} role="alert">
            <div>
              <strong>Execution Error:</strong> {executionError}
            </div>
          </div>
        )}

        {executionResult && (
          <div style={{ marginTop: '20px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '8px' }}>
              Execution Status:
            </h3>

            {renderStatusPipeline(executionResult.status)}

            <div className="code-block">
              <div>
                <strong>Execution ID:</strong> {executionResult.execution_id}
              </div>
              <div>
                <strong>Action:</strong> {executionResult.action_name}
              </div>
              <div>
                <strong>Status:</strong> {executionResult.status}
              </div>
              <div>
                <strong>Correlation ID:</strong> {executionResult.correlation_id}
              </div>
              {executionResult.policy_version !== null && executionResult.policy_version !== undefined && (
                <div>
                  <strong>Policy Version:</strong> v{executionResult.policy_version}
                </div>
              )}
              {executionResult.result && (
                <div style={{ marginTop: '8px' }}>
                  <strong>Result Payload:</strong>
                  <pre style={{ margin: '4px 0 0 0', overflowX: 'auto' }}>
                    {JSON.stringify(executionResult.result, null, 2)}
                  </pre>
                </div>
              )}
              {executionResult.error_message && (
                <div style={{ marginTop: '8px', color: 'var(--danger)' }}>
                  <strong>Error Message:</strong> {executionResult.error_message}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Action History */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h2 className="card-title" style={{ margin: 0 }}>
            Action Execution History
          </h2>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={loadHistory}
            disabled={loadingHistory}
          >
            {loadingHistory ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {history.length === 0 ? (
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
            No recorded action executions for your tenant yet.
          </p>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Status</th>
                  <th>Parameters</th>
                  <th>Result / Error</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <code>{item.action_name}</code>
                    </td>
                    <td>{getStatusBadge(item.status)}</td>
                    <td>
                      <code style={{ fontSize: '12px' }}>
                        {JSON.stringify(item.parameters)}
                      </code>
                    </td>
                    <td>
                      {item.error_message ? (
                        <span style={{ color: 'var(--danger)', fontSize: '13px' }}>
                          {item.error_message}
                        </span>
                      ) : item.result ? (
                        <code style={{ fontSize: '12px' }}>
                          {JSON.stringify(item.result)}
                        </code>
                      ) : (
                        <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>—</span>
                      )}
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {new Date(item.created_at).toLocaleString()}
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
