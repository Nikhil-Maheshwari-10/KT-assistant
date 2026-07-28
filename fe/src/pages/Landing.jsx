import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { createSession } from '../api/client';
import { GitBranch, Route, BarChart2, FileText, Database, MessageSquare, Download } from 'lucide-react';

const FEATURES = [
  {
    icon: <GitBranch size={24} />,
    colorClass: 'blue',
    title: 'GitHub Repository Ingestion',
    desc: 'Point it at any public GitHub repository. Branch selection, priority-based file fetching, and smart overlapping chunking built-in.',
  },
  {
    icon: <Route size={24} />,
    colorClass: 'teal',
    title: 'Intent-Routed Q&A',
    desc: 'Questions are automatically classified — structural, content, operational, or broad — and routed to the right data source for precise answers.',
  },
  {
    icon: <BarChart2 size={24} />,
    colorClass: 'green',
    title: 'Real-Time Coverage Scoring',
    desc: 'Track knowledge coverage across System Overview, Architecture & Data Flow, and Operations & Reliability with live confidence scores.',
  },
  {
    icon: <FileText size={24} />,
    colorClass: 'purple',
    title: 'Professional Document Export',
    desc: 'Generate exhaustive KT reports with Mermaid diagrams, risk matrices, and API tables. Download as polished PDF or DOCX.',
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleStart() {
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await createSession();
      navigate(`/chat/${session_id}`);
    } catch (e) {
      setError('Could not reach the backend. Make sure the API is running on port 8000.');
      setLoading(false);
    }
  }

  return (
    <main className="landing">
      <div className="landing-bg" />

      {/* Nav */}
      <nav className="landing-nav">
        <div className="landing-nav-logo">🧠</div>
        <span className="landing-nav-brand">KT Assistant</span>
        <div className="landing-nav-spacer" />
      </nav>

      {/* Hero */}
      <section className="landing-hero">

        <h1 className="landing-h1">
          Transform your codebase into&nbsp;
          <span className="gradient-text">professional documentation</span>
        </h1>

        <p className="landing-desc">
          Ingest any GitHub repository or uploaded document. Get real-time coverage
          scoring, semantic Q&amp;A, and export publication-ready KT reports in seconds.
        </p>

        <div className="landing-cta-group">
          <button
            className="btn btn-primary btn-lg"
            onClick={handleStart}
            disabled={loading}
            id="start-session-btn"
          >
            {loading ? (
              <>
                <span className="spinner spinner-sm" />
                Initializing session…
              </>
            ) : (
              <>🚀 Start KT Session</>
            )}
          </button>
          <a
            href="https://github.com/Nikhil-Maheshwari-10/KT-assistant"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary btn-lg"
          >
            View on GitHub
          </a>
        </div>

        {error && (
          <div className="alert alert-error mt-3" style={{ maxWidth: 480 }}>
            ⚠ {error}
          </div>
        )}
      </section>

      {/* Feature cards */}
      <section className="landing-features slide-up">
        {FEATURES.map((f) => (
          <div className="feature-card" key={f.title}>
            <div className={`feature-icon ${f.colorClass}`}>{f.icon}</div>
            <div className="feature-title">{f.title}</div>
            <p className="feature-desc">{f.desc}</p>
          </div>
        ))}
      </section>

      {/* How it Works */}
      <section className="landing-how-it-works slide-up" style={{ animationDelay: '0.1s' }}>
        <h2 className="section-title">How It Works</h2>
        <div className="steps-container">
          <div className="step-card">
            <div className="step-number">1</div>
            <div className="step-icon"><Database size={32} /></div>
            <h3>Ingest Your Codebase</h3>
            <p>Paste a GitHub URL or upload your files. We instantly parse, chunk, and index the data into our vector database.</p>
          </div>
          <div className="step-card">
            <div className="step-number">2</div>
            <div className="step-icon"><MessageSquare size={32} /></div>
            <h3>Ask & Analyze</h3>
            <p>Chat with the AI to understand complex logic, dependencies, and architectural flows in real-time.</p>
          </div>
          <div className="step-card">
            <div className="step-number">3</div>
            <div className="step-icon"><Download size={32} /></div>
            <h3>Export Documentation</h3>
            <p>Once you're satisfied with the knowledge transfer, generate and download a comprehensive, beautifully formatted report.</p>
          </div>
        </div>
      </section>

    </main>
  );
}
