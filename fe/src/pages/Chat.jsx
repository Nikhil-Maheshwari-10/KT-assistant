import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getSession,
  getMessages,
  deleteSession,
} from '../api/client';
import Sidebar from '../components/Sidebar';
import ChatPane from '../components/ChatPane';
import DocumentPane from '../components/DocumentPane';
import { Menu, PanelLeft } from 'lucide-react';

export default function Chat() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingSession, setLoadingSession] = useState(true);
  const [activeTab, setActiveTab] = useState('chat'); // 'chat' | 'document'
  const [generatedDoc, setGeneratedDoc] = useState(null); // { markdown, generated_at }
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sessionError, setSessionError] = useState(null);

  // Load session + message history
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sess, msgs] = await Promise.all([
          getSession(sessionId),
          getMessages(sessionId),
        ]);
        if (!cancelled) {
          setSession(sess);
          setMessages(msgs.messages || []);
        }
      } catch (e) {
        if (!cancelled) setSessionError(e.message);
      } finally {
        if (!cancelled) setLoadingSession(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  const handleSessionUpdate = useCallback((updatedSessionOrFn) => {
    if (typeof updatedSessionOrFn === 'function') {
      setSession((prev) => updatedSessionOrFn(prev));
    } else {
      setSession(updatedSessionOrFn);
    }
  }, []);

  const handleNewMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const handleDocGenerated = useCallback((doc) => {
    setGeneratedDoc(doc);
    setActiveTab('document');
  }, []);

  const handleClearSession = useCallback(() => {
    navigate('/');
  }, [navigate]);

  if (loadingSession) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', flexDirection: 'column', gap: 16 }}>
        <span className="spinner spinner-lg" />
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading session…</span>
      </div>
    );
  }

  if (sessionError) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', flexDirection: 'column', gap: 16 }}>
        <div style={{ fontSize: '2.5rem' }}>⚠️</div>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>{sessionError}</div>
        <button className="btn btn-secondary" onClick={() => navigate('/')}>← Back to Home</button>
      </div>
    );
  }

  return (
    <div className="app-layout">
      <div style={{ display: sidebarOpen ? 'flex' : 'none' }}>
        <Sidebar
          session={session}
          sessionId={sessionId}
          onSessionUpdate={handleSessionUpdate}
          onNewMessage={handleNewMessage}
          onDocGenerated={handleDocGenerated}
          onClearSession={handleClearSession}
          generatedDoc={generatedDoc}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          onToggleSidebar={() => setSidebarOpen(false)}
        />
      </div>

      <div className="main-area">
        {/* Top bar */}
        <div className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {!sidebarOpen && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setSidebarOpen(true)}
                title="Open Sidebar"
                style={{ padding: '4px' }}
              >
                <PanelLeft size={20} />
              </button>
            )}
            <span className="topbar-title">
              {activeTab === 'chat' ? '💬 Chat' : '📄 KT Document'}
            </span>
          </div>
          <div className="topbar-spacer" />
          <div className="tab-bar">
            <button
              id="tab-chat"
              className={`tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => setActiveTab('chat')}
            >
              💬 Chat
            </button>
            <button
              id="tab-doc"
              className={`tab-btn ${activeTab === 'document' ? 'active' : ''}`}
              onClick={() => setActiveTab('document')}
            >
              📄 Document
            </button>
          </div>
        </div>

        {/* Content */}
        {activeTab === 'chat' ? (
          <ChatPane
            sessionId={sessionId}
            session={session}
            messages={messages}
            onNewMessage={handleNewMessage}
            onSessionUpdate={handleSessionUpdate}
          />
        ) : (
          <DocumentPane
            sessionId={sessionId}
            session={session}
            generatedDoc={generatedDoc}
            onDocGenerated={handleDocGenerated}
          />
        )}
      </div>
    </div>
  );
}
