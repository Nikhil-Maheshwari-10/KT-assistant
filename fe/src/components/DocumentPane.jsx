import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { generateDocument, getPdfUrl, getDocxUrl } from '../api/client';
import MermaidDiagram from './MermaidDiagram';

// Custom code block renderer: renders mermaid fences as diagrams
function CodeBlock({ className, children, ...props }) {
  const lang = className?.replace('language-', '') || '';
  if (lang === 'mermaid') {
    return <MermaidDiagram chart={String(children).trim()} />;
  }
  return (
    <code className={className} {...props}>
      {children}
    </code>
  );
}

const MD_COMPONENTS = { code: CodeBlock };

export default function DocumentPane({ sessionId, session, generatedDoc, onDocGenerated }) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const hasContent = session?.topics?.some((t) => t.confidence_score > 0);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const doc = await generateDocument(sessionId);
      onDocGenerated(doc);
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  }

  if (!generatedDoc) {
    return (
      <div className="doc-panel">
        <div className="doc-placeholder">
          <div className="doc-placeholder-icon">📄</div>
          <h3 style={{ fontSize: '1rem', color: 'var(--text-primary)', fontWeight: 700 }}>
            No document generated yet
          </h3>
          <p>
            {hasContent
              ? 'Your session has indexed knowledge. Click the button below to generate a comprehensive KT document.'
              : 'Ingest a GitHub repository or document first, then generate your KT report here.'}
          </p>
          {hasContent && (
            <button
              className="btn btn-primary"
              onClick={handleGenerate}
              disabled={generating}
              id="generate-doc-main-btn"
            >
              {generating ? (
                <><span className="spinner spinner-sm" /> Generating…</>
              ) : (
                '✨ Generate KT Document'
              )}
            </button>
          )}
          {error && (
            <div className="alert alert-error" style={{ maxWidth: 440, textAlign: 'left' }}>
              ⚠ {error}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="doc-panel">
      {/* Toolbar */}
      <div className="doc-toolbar">
        <span className="doc-toolbar-title">KT Document</span>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          Generated {new Date(generatedDoc.generated_at).toLocaleString()}
        </span>
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleGenerate}
          disabled={generating}
          title="Regenerate document"
          id="regenerate-doc-btn"
        >
          {generating ? <span className="spinner spinner-sm" /> : '↺ Regenerate'}
        </button>
        <a
          href={getPdfUrl(sessionId)}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-secondary btn-sm"
          id="export-pdf-btn"
        >
          ⬇ PDF
        </a>
        <a
          href={getDocxUrl(sessionId)}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-secondary btn-sm"
          id="export-docx-btn"
        >
          ⬇ DOCX
        </a>
      </div>

      {/* Document body */}
      <div className="doc-body">
        <div className="doc-body-inner">
          {/* Coverage summary */}
          {session?.topics && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 10,
                marginBottom: 32,
              }}
            >
              {session.topics.map((t) => (
                <div
                  key={t.id}
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '12px 14px',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: '1.2rem', fontWeight: 800, color: t.confidence_score >= 80 ? 'var(--success)' : 'var(--accent-1)' }}>
                    {t.confidence_score}%
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: 3 }}>
                    {t.name}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="md-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
              {generatedDoc.markdown}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}
