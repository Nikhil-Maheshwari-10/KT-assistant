import { useState, useRef, useEffect } from 'react';
import { getBranches, ingestGithub, ingestFile, generateDocument, getPdfUrl, getDocxUrl, getSessions, createSession, deleteSession } from '../api/client';
import CoverageCard from './CoverageCard';
import FileTree from './FileTree';
import { PlusCircle, MessageSquare, PanelLeftClose, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function Sidebar({
  session,
  sessionId,
  onSessionUpdate,
  onNewMessage,
  onDocGenerated,
  onClearSession,
  generatedDoc,
  activeTab,
  setActiveTab,
  onToggleSidebar,
}) {
  // Default to 'status' if we already have ingested content, otherwise 'ingest'
  const [tab, setTab] = useState(session?.file_manifest?.length > 0 ? 'status' : 'ingest'); 
  const navigate = useNavigate();

  // GitHub ingest state
  const [githubUrl, setGithubUrl] = useState('');
  const [githubToken, setGithubToken] = useState('');
  const [isPrivate, setIsPrivate] = useState(false);
  const [branches, setBranches] = useState([]);
  const [selectedBranch, setSelectedBranch] = useState('');
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestLog, setIngestLog] = useState([]);
  const [ingestError, setIngestError] = useState(null);
  const abortRef = useRef(null);

  // File upload state
  const [uploadingFile, setUploadingFile] = useState(false);
  const [fileError, setFileError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // Doc generation
  const [generatingDoc, setGeneratingDoc] = useState(false);
  const [docError, setDocError] = useState(null);

  const hasContent = session?.topics?.some((t) => t.confidence_score > 0);
  const hasIngested = (session?.file_manifest?.length ?? 0) > 0;

  // History state
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  /* ── Branch fetch ────────────────────────────── */
  async function handleLoadBranches() {
    if (!githubUrl.trim()) return;
    setLoadingBranches(true);
    setBranches([]);
    setSelectedBranch('');
    setIngestError(null);
    try {
      const data = await getBranches(sessionId, githubUrl.trim(), githubToken.trim());
      setBranches(data.branches || []);
      if (data.branches?.length) setSelectedBranch(data.branches[0]);
    } catch (e) {
      setIngestError(e.message);
    } finally {
      setLoadingBranches(false);
    }
  }

  /* ── History fetch ─────────────────────────────── */
  async function handleLoadHistory() {
    if (history.length === 0) setLoadingHistory(true);
    try {
      const data = await getSessions();
      setHistory(data.sessions || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingHistory(false);
    }
  }

  // Load history when tab becomes active
  useEffect(() => {
    if (tab === 'history') {
      handleLoadHistory();
    }
  }, [tab]);

  async function handleNewChat() {
    // If the current session is already completely empty, don't create a new one!
    // Just switch to the ingest tab so they can use the current empty session.
    if (!hasIngested) {
      setTab('ingest');
      return;
    }

    try {
      const { session_id } = await createSession();
      navigate(`/chat/${session_id}`);
      setTab('ingest');
    } catch (e) {
      alert('Failed to create new chat: ' + e.message);
    }
  }

  async function handleDeleteHistoryItem(e, id) {
    e.stopPropagation(); // prevent clicking the button
    try {
      await deleteSession(id);
      if (id === sessionId) {
        // If deleting current session, find the next available session to switch to
        const remaining = history.filter(s => s.id !== id);
        if (remaining.length > 0) {
          navigate(`/chat/${remaining[0].id}`);
        } else {
          // If no sessions left, clear it and go to landing
          onClearSession();
        }
      } else {
        // Refresh history
        handleLoadHistory();
      }
    } catch (err) {
      alert('Failed to delete session: ' + err.message);
    }
  }

  /* ── GitHub ingest ───────────────────────────── */
  async function handleIngestGithub() {
    if (!githubUrl.trim() || !selectedBranch) return;

    let targetSessionId = sessionId;

    // If the current session ALREADY has a repo ingested, we shouldn't overwrite it.
    // Instead, auto-create a new isolated session for this new repository!
    if (hasIngested) {
      try {
        const { session_id } = await createSession();
        targetSessionId = session_id;
        navigate(`/chat/${session_id}`);
      } catch (err) {
        alert("Failed to auto-create new session for new repository: " + err.message);
        return;
      }
    }

    setIngesting(true);
    setIngestLog([]);
    setIngestError(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await ingestGithub(targetSessionId, githubUrl.trim(), selectedBranch, githubToken.trim(), (evt) => {
        if (evt.type === 'progress') {
          setIngestLog((prev) => [...prev, { kind: 'info', text: evt.message }]);
        } else if (evt.type === 'topic_update') {
          setIngestLog((prev) => [
            ...prev,
            { kind: 'info', text: `📊 ${evt.topic_name}: ${evt.score}%` },
          ]);
          // Refresh session topics from event data
          onSessionUpdate((prev) => ({
            ...prev,
            topics: prev.topics.map((t) =>
              t.id === evt.topic_id
                ? { ...t, confidence_score: evt.score, missing_sections: evt.missing_sections || [] }
                : t
            ),
            overall_confidence: Math.round(
              prev.topics.reduce((s, t) =>
                s + (t.id === evt.topic_id ? evt.score : t.confidence_score), 0
              ) / prev.topics.length
            ),
          }));
        } else if (evt.type === 'done') {
          if (evt.status === 'Success') {
            setIngestLog((prev) => [...prev, { kind: 'success', text: `✅ Done — ${evt.files_fetched} files indexed.` }]);
            if (evt.session) onSessionUpdate(evt.session);
            onNewMessage({
              role: 'assistant',
              content: `🐙 **GitHub Repository Ingested:** \`${evt.owner}/${evt.repo}\` (branch: \`${evt.branch}\`)\n\nI've successfully analyzed the codebase. Feel free to ask me anything about its architecture, flow, or code details!`,
              timestamp: new Date().toISOString(),
            });
            setTab('status');
          } else {
            setIngestLog((prev) => [...prev, { kind: 'error', text: '❌ Ingestion failed.' }]);
          }
        } else if (evt.type === 'error') {
          setIngestLog((prev) => [...prev, { kind: 'error', text: `❌ ${evt.message}` }]);
        }
      }, ctrl.signal);
    } catch (e) {
      if (e.name !== 'AbortError') setIngestError(e.message);
    } finally {
      setIngesting(false);
    }
  }

  /* ── ZIP File upload ─────────────────────────────── */
  async function handleFile(file) {
    if (!file) return;
    if (!file.name.endsWith('.zip')) {
      setFileError('Only ZIP archives are supported.');
      return;
    }
    setUploadingFile(true);
    setFileError(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await ingestFile(sessionId, file, (evt) => {
        if (evt.type === 'topic_update') {
          onSessionUpdate((prev) => ({
            ...prev,
            topics: prev.topics.map((t) =>
              t.id === evt.topic_id
                ? { ...t, confidence_score: evt.score, missing_sections: evt.missing_sections || [] }
                : t
            ),
            overall_confidence: Math.round(
              prev.topics.reduce((s, t) =>
                s + (t.id === evt.topic_id ? evt.score : t.confidence_score), 0
              ) / prev.topics.length
            ),
          }));
        } else if (evt.type === 'done') {
          if (evt.status === 'Success') {
            if (evt.session) onSessionUpdate(evt.session);
            onNewMessage({
              role: 'assistant',
              content: `🐙 **ZIP Archive Ingested:** \`${evt.repo}\`\n\nI've successfully analyzed the codebase. Feel free to ask me anything about its architecture, flow, or code details!`,
              timestamp: new Date().toISOString(),
            });
            setTab('status');
          } else {
            setFileError('Ingestion failed.');
          }
        } else if (evt.type === 'error') {
          setFileError(`❌ ${evt.message}`);
        }
      }, ctrl.signal);
    } catch (e) {
      if (e.name !== 'AbortError') setFileError(e.message);
    } finally {
      setUploadingFile(false);
    }
  }

  /* ── Document generation ─────────────────────── */
  async function handleGenerateDoc() {
    setGeneratingDoc(true);
    setDocError(null);
    try {
      const doc = await generateDocument(sessionId);
      onDocGenerated(doc);
    } catch (e) {
      setDocError(e.message);
    } finally {
      setGeneratingDoc(false);
    }
  }

  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">🧠</div>
          <div>
            <h1>KT Assistant</h1>
            <span>Knowledge Transfer Engine</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button 
            className="btn btn-secondary btn-sm" 
            onClick={handleNewChat}
            title="New Chat"
            style={{ padding: '6px' }}
          >
            <PlusCircle size={18} />
          </button>
          <button 
            className="btn btn-secondary btn-sm" 
            onClick={onToggleSidebar}
            title="Collapse Sidebar"
            style={{ padding: '6px' }}
          >
            <PanelLeftClose size={18} />
          </button>
        </div>
      </div>

      {/* Tab bar — only show Status tab once something is ingested */}
      <div style={{ padding: '10px 16px 0', flexShrink: 0 }}>
        <div className="tab-bar" style={{ width: '100%' }}>
          <button
            className={`tab-btn ${tab === 'history' ? 'active' : ''}`}
            style={{ flex: 1, justifyContent: 'center' }}
            onClick={() => setTab('history')}
            id="sidebar-tab-history"
          >
            🕰️ History
          </button>
          {hasIngested && (
            <button
              className={`tab-btn ${tab === 'status' ? 'active' : ''}`}
              style={{ flex: 1, justifyContent: 'center' }}
              onClick={() => setTab('status')}
              id="sidebar-tab-status"
            >
              📊 Status
            </button>
          )}
          <button
            className={`tab-btn ${tab === 'ingest' ? 'active' : ''}`}
            style={{ flex: 1, justifyContent: 'center' }}
            onClick={() => setTab('ingest')}
            id="sidebar-tab-ingest"
          >
            📥 Ingest
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="sidebar-body">
        {tab === 'status' && (
          <>
            <CoverageCard session={session} />
            <FileTree files={session?.file_manifest?.filter(f => !f.startsWith('__REPO__:'))} />

            {/* Generate Document */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">Export</div>
              <button
                className="btn btn-primary btn-full"
                disabled={!hasContent || generatingDoc}
                onClick={handleGenerateDoc}
                id="generate-doc-btn"
              >
                {generatingDoc ? (
                  <><span className="spinner spinner-sm" /> Generating…</>
                ) : (
                  '📄 Generate KT Document'
                )}
              </button>
              {docError && (
                <div className="alert alert-error text-xs">{docError}</div>
              )}
              {!hasContent && (
                <p className="text-xs text-muted" style={{ textAlign: 'center' }}>
                  Ingest content first to enable document generation
                </p>
              )}
            </div>
          </>
        )}

        {tab === 'ingest' && (
          <>
            {/* GitHub */}
            <div className="sidebar-section">
              <div className="sidebar-section-title">GitHub Repository</div>
              <div className="form-group" style={{ marginBottom: '8px' }}>
                <input
                  className="form-input"
                  id="github-url-input"
                  placeholder="https://github.com/owner/repo"
                  value={githubUrl}
                  onChange={(e) => { setGithubUrl(e.target.value); setBranches([]); setIsPrivate(false); setIngestError(null); }}
                  disabled={ingesting}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <input 
                  type="checkbox" 
                  id="private-repo-toggle"
                  className="form-checkbox"
                  checked={isPrivate}
                  onChange={(e) => {
                    setIsPrivate(e.target.checked);
                    if (!e.target.checked) setGithubToken('');
                  }}
                  disabled={ingesting}
                />
                <label htmlFor="private-repo-toggle" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', cursor: 'pointer', userSelect: 'none' }}>
                  🔒 Private Repository
                </label>
              </div>

              {isPrivate && (
                <div className="form-group">
                  <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>GitHub PAT Token</span>
                    <a href="https://github.com/settings/tokens/new?scopes=repo" target="_blank" rel="noreferrer" style={{ fontSize: '0.75rem', color: 'var(--primary)', textDecoration: 'none' }}>Get Token ↗</a>
                  </label>
                  <input
                    type="password"
                    className="form-input"
                    id="github-token-input"
                    placeholder="ghp_xxxxxxxxxxxx"
                    value={githubToken}
                    onChange={(e) => { setGithubToken(e.target.value); setIngestError(null); }}
                    disabled={ingesting}
                  />
                  <div className="text-xs text-muted mt-1">Required for private repos. Never stored.</div>
                </div>
              )}

              <button
                className="btn btn-secondary btn-full btn-sm"
                onClick={handleLoadBranches}
                disabled={!githubUrl.trim() || (isPrivate && !githubToken.trim()) || loadingBranches || ingesting}
                id="load-branches-btn"
              >
                {loadingBranches ? (
                  <><span className="spinner spinner-sm" /> Loading…</>
                ) : '⎇ Load Branches'}
              </button>

              {branches.length > 0 && (
                <>
                  <div className="form-group">
                    <label className="form-label">Branch</label>
                    <select
                      className="form-select"
                      id="branch-select"
                      value={selectedBranch}
                      onChange={(e) => setSelectedBranch(e.target.value)}
                      disabled={ingesting}
                    >
                      {branches.map((b) => (
                        <option key={b} value={b}>{b}</option>
                      ))}
                    </select>
                  </div>

                  <button
                    className="btn btn-primary btn-full"
                    onClick={handleIngestGithub}
                    disabled={ingesting || (isPrivate && !githubToken.trim())}
                    id="analyse-repo-btn"
                  >
                    {ingesting ? (
                      <><span className="spinner spinner-sm" /> Analysing…</>
                    ) : '🚀 Analyse Repository'}
                  </button>

                  {ingesting && (
                    <button
                      className="btn btn-ghost btn-sm btn-full"
                      onClick={() => abortRef.current?.abort()}
                    >
                      Cancel
                    </button>
                  )}
                </>
              )}

              {ingestError && (
                <div className="alert alert-error text-xs">{ingestError}</div>
              )}


            </div>

            <div className="divider" />

            <div className="sidebar-section">
              <div className="sidebar-section-title">Upload ZIP Archive</div>

              <div
                className={`upload-zone ${dragOver ? 'drag-over' : ''} ${uploadingFile ? 'uploading' : ''}`}
                style={ingesting ? { opacity: 0.5, pointerEvents: 'none', cursor: 'not-allowed' } : {}}
                id="file-upload-zone"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  handleFile(e.dataTransfer.files[0]);
                }}
              >
                {uploadingFile ? (
                  <div className="flex items-center justify-center gap-2" style={{ padding: '8px 0', flexDirection: 'column' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="spinner spinner-sm" />
                      <span className="upload-zone-text">Extracting & Analysing…</span>
                    </div>
                    <button 
                      className="btn btn-ghost btn-sm" 
                      onClick={(e) => { e.stopPropagation(); abortRef.current?.abort(); }}
                      style={{ marginTop: '8px' }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="upload-zone-icon">📁</div>
                    <div className="upload-zone-text">Drop ZIP here or click to browse</div>
                    <div className="upload-zone-hint">Repository archive — up to 50 MB</div>
                  </>
                )}
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                style={{ display: 'none' }}
                id="file-input"
                disabled={ingesting}
                onChange={(e) => handleFile(e.target.files[0])}
              />

              {fileError && (
                <div className="alert alert-error text-xs">{fileError}</div>
              )}
            </div>
            </>
          )}

          {tab === 'history' && (
            <div className="sidebar-section">
              <div className="sidebar-section-title">Recent Chats</div>
              {loadingHistory ? (
                <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)' }}>
                  <span className="spinner spinner-sm" /> Loading history...
                </div>
              ) : history.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)' }}>
                  No past sessions found.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {history.map((s) => {
                    // Derive a name from the file manifest, or default to standard name
                    let title = "New Chat";
                    if (s.file_manifest && s.file_manifest.length > 0) {
                      const firstFile = s.file_manifest[0];
                      if (firstFile.startsWith('__REPO__:')) {
                        title = firstFile.substring('__REPO__:'.length);
                      } else {
                        // E.g. "Nikhil-Maheshwari-10/KT-assistant/main.py" -> "KT-assistant"
                        const parts = firstFile.split('/');
                        title = parts.length > 1 ? parts[1] : parts[0];
                      }
                    }
                    
                    const date = new Date(s.updated_at).toLocaleDateString();
                    
                    return (
                      <div key={s.id} style={{ display: 'flex', gap: '4px' }}>
                        <button
                          className={`btn ${s.id === sessionId ? 'btn-primary' : 'btn-secondary'}`}
                          style={{ flex: 1, textAlign: 'left', display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}
                          onClick={() => navigate(`/chat/${s.id}`)}
                        >
                          <MessageSquare size={16} style={{ flexShrink: 0 }} />
                          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <div style={{ fontWeight: '500' }}>{title}</div>
                            <div style={{ fontSize: '0.75rem', opacity: 0.7 }}>{date}</div>
                          </div>
                        </button>
                        <button
                          className="btn btn-danger-ghost"
                          style={{ padding: '8px', flexShrink: 0 }}
                          onClick={(e) => handleDeleteHistoryItem(e, s.id)}
                          title="Delete Session"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
  );
}
