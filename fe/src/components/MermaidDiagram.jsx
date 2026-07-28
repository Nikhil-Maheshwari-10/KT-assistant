import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

// Initialize mermaid once
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    primaryColor: '#7c3aed',
    primaryTextColor: '#e2e8f0',
    primaryBorderColor: '#6d28d9',
    lineColor: '#94a3b8',
    secondaryColor: '#1e293b',
    tertiaryColor: '#0f172a',
    background: '#0d1117',
    mainBkg: '#1e293b',
    nodeBorder: '#6d28d9',
    clusterBkg: '#1e293b',
    titleColor: '#e2e8f0',
    edgeLabelBackground: '#1e293b',
    fontFamily: 'Inter, system-ui, sans-serif',
  },
  securityLevel: 'loose',
});

let diagramCounter = 0;

export default function MermaidDiagram({ chart }) {
  const ref = useRef(null);
  const [error, setError] = useState(null);
  const [svg, setSvg] = useState(null);

  useEffect(() => {
    if (!chart) return;
    const id = `mermaid-diagram-${++diagramCounter}`;
    setError(null);

    mermaid
      .render(id, chart)
      .then(({ svg: renderedSvg }) => {
        setSvg(renderedSvg);
      })
      .catch((err) => {
        setError(err?.message || 'Failed to render diagram');
        setSvg(null);
      });
  }, [chart]);

  if (error) {
    return (
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          padding: '12px 16px',
          margin: '12px 0',
        }}
      >
        <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginBottom: 6 }}>
          ⚠ Mermaid render error — showing source
        </div>
        <pre style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {chart}
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          padding: '24px',
          margin: '12px 0',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.8rem',
        }}
      >
        <span className="spinner spinner-sm" style={{ display: 'inline-block', marginRight: 8 }} />
        Rendering diagram…
      </div>
    );
  }

  return (
    <div
      ref={ref}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '16px',
        margin: '12px 0',
        overflowX: 'auto',
        textAlign: 'center',
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
