import { useState, useEffect, useRef, useCallback } from 'react';
import { sendChatMessage } from '../api/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function MessageBubble({ msg, streaming }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`message-row ${isUser ? 'user' : 'assistant'} fade-in`}>
      {!isUser && (
        <div className="avatar assistant">🧠</div>
      )}
      <div className="message-bubble">
        <div className="message-content">
          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
          ) : (
            <div className="md-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
                {msg.content}
              </ReactMarkdown>
            </div>
          )}
          {streaming && (
            <span
              style={{
                display: 'inline-block',
                width: 2,
                height: '1.1em',
                background: 'var(--accent-1)',
                verticalAlign: 'text-bottom',
                marginLeft: 2,
                animation: 'pulse 0.8s ease-in-out infinite',
              }}
            />
          )}
        </div>
        <div className="message-meta">
          <span>{formatTime(msg.timestamp)}</span>
        </div>
      </div>
      {isUser && (
        <div className="avatar user">You</div>
      )}
    </div>
  );
}

const INTENT_LABELS = {
  STRUCTURAL: 'file structure',
  CONTENT: 'code & logic',
  OPERATIONAL: 'operations & deployment',
  BROAD: 'full system knowledge',
};

function ThinkingIndicator({ phase, intents }) {
  const searchLabel = intents?.length
    ? intents.map((i) => INTENT_LABELS[i] || i.toLowerCase()).join(' & ')
    : 'knowledge base';

  const steps = [
    { key: 'classifying', icon: '🔍', text: 'Classifying your question…' },
    { key: 'searching',   icon: '📂', text: `Searching ${searchLabel}…` },
    { key: 'generating',  icon: '✍️',  text: 'Generating answer…' },
  ];

  const activeIdx = steps.findIndex((s) => s.key === phase);

  return (
    <div className="message-row assistant fade-in">
      <div className="avatar assistant">🧠</div>
      <div className="message-bubble">
        <div className="thinking-steps">
          {steps.map((step, i) => {
            const isDone    = i < activeIdx;
            const isActive  = i === activeIdx;
            return (
              <div key={step.key} className={`thinking-step ${isDone ? 'done' : isActive ? 'active' : 'pending'}`}>
                <span className="thinking-step-icon">
                  {isDone ? '✅' : step.icon}
                </span>
                <span className="thinking-step-text">{step.text}</span>
                {isActive && <span className="thinking-spinner" />}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function ChatPane({
  sessionId,
  session,
  messages,
  onNewMessage,
  onSessionUpdate,
}) {
  const [localMessages, setLocalMessages] = useState(messages);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamingId, setStreamingId] = useState(null);
  const [typing, setTyping] = useState(false);
  const [thinkingPhase, setThinkingPhase] = useState('classifying'); // classifying | searching | generating
  const [thinkingIntents, setThinkingIntents] = useState([]);
  const [error, setError] = useState(null);
  const feedRef = useRef(null);
  const textareaRef = useRef(null);
  const abortRef = useRef(null);

  // Sync external messages
  useEffect(() => {
    setLocalMessages(messages);
  }, [messages]);

  // Auto-scroll
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [localMessages, typing]);

  const hasContent =
    session?.topics?.some((t) => t.confidence_score > 0) ||
    (session?.file_manifest?.length ?? 0) > 0;

  const sendMessage = useCallback(async () => {
    const q = input.trim();
    if (!q || streaming) return;

    const userMsg = {
      role: 'user',
      content: q,
      timestamp: new Date().toISOString(),
    };

    setLocalMessages((prev) => [...prev, userMsg]);
    setInput('');
    setError(null);
    setTyping(true);
    setThinkingPhase('classifying');
    setThinkingIntents([]);
    setStreaming(true);

    let assistantAppended = false;
    let fullContent = '';
    let detectedIntents = [];

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await sendChatMessage(sessionId, q, (evt) => {
        if (evt.type === 'intent') {
          // Intent classified — update indicator to "searching" phase
          detectedIntents = evt.intents || [];
          setThinkingIntents(detectedIntents);
          setThinkingPhase('searching');
        } else if (evt.type === 'token') {
          fullContent += evt.content;
          // First token: update to generating phase briefly, then show answer
          if (!assistantAppended) {
            assistantAppended = true;
            setThinkingPhase('generating');
            // Small visual pause so the user sees "Generating answer…" step
            setTimeout(() => {
              setTyping(false);
              setLocalMessages((prev) => [
              ...prev,
              {
                role: 'assistant',
                content: fullContent,
                timestamp: new Date().toISOString(),
                intents: detectedIntents,
              },
            ]);
            }, 400);
          } else {
            setLocalMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = { ...last, content: fullContent };
              }
              return updated;
            });
          }
        } else if (evt.type === 'done') {
          if (evt.status === 'Success') {
            const finalAnswer = evt.full_answer || fullContent;
            const finalIntents = evt.intents || detectedIntents;
            setLocalMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: finalAnswer,
                  intents: finalIntents,
                };
              }
              return updated;
            });
          }
        } else if (evt.type === 'error') {
          setError(evt.message);
          setTyping(false);
        }
      }, ctrl.signal);
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message);
      }
    } finally {
      setStreaming(false);
      setTyping(false);
      setStreamingId(null);
      textareaRef.current?.focus();
    }
  }, [input, streaming, sessionId]);

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function adjustHeight(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  return (
    <>
      {/* Messages */}
      <div className="chat-feed" ref={feedRef}>
        {localMessages.length === 0 && !hasContent && (
          <div className="empty-chat">
            <div className="empty-chat-icon">💬</div>
            <h3>Start by ingesting content</h3>
            <p>
              Upload a GitHub repository or a PDF/TXT document from the sidebar.
              Once content is indexed, you can ask anything about the codebase.
            </p>
          </div>
        )}

        {localMessages.length === 0 && hasContent && (
          <div className="empty-chat">
            <div className="empty-chat-icon">🤔</div>
            <h3>Ask anything</h3>
            <p>
              Content has been indexed. Try asking about the architecture,
              deployment steps, or how specific components work.
            </p>
          </div>
        )}

        {localMessages.map((msg, i) => (
          <MessageBubble
            key={i}
            msg={msg}
            streaming={streaming && i === localMessages.length - 1 && msg.role === 'assistant'}
          />
        ))}

        {typing && <ThinkingIndicator phase={thinkingPhase} intents={thinkingIntents} />}

        {error && (
          <div className="alert alert-error" style={{ maxWidth: 600, alignSelf: 'center' }}>
            ⚠ {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="chat-input-area">
        <div className="chat-input-row">
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            id="chat-input"
            rows={1}
            placeholder={
              hasContent
                ? 'Ask anything about the codebase… (Enter to send, Shift+Enter for newline)'
                : 'Ingest content from the sidebar to start chatting…'
            }
            value={input}
            disabled={!hasContent || streaming}
            onChange={(e) => {
              setInput(e.target.value);
              adjustHeight(e.target);
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            className="send-btn"
            id="send-btn"
            onClick={sendMessage}
            disabled={!input.trim() || !hasContent || streaming}
            title="Send message"
          >
            {streaming ? (
              <span className="spinner spinner-sm" style={{ borderTopColor: 'white' }} />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
        <div className="chat-input-hint">
          Intent-routed Q&amp;A · Semantic search over {session?.file_manifest?.length ?? 0} files
        </div>
      </div>
    </>
  );
}
