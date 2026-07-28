const KT_THRESHOLD = 80;

function statusClass(score) {
  if (score >= KT_THRESHOLD) return 'complete';
  if (score > 0) return 'partial';
  return 'empty';
}

function statusIcon(score) {
  if (score >= KT_THRESHOLD) return '✅';
  if (score > 0) return '⏳';
  return '📝';
}

export default function CoverageCard({ session }) {
  if (!session) return null;

  const overall = session.overall_confidence ?? 0;
  const topics = session.topics ?? [];

  return (
    <div className="coverage-card">
      <div className="coverage-header">
        <span className="coverage-label">Overall Coverage</span>
        <span className="coverage-pct">{overall}%</span>
      </div>

      <div className="coverage-bar-outer">
        <div className="coverage-bar-inner" style={{ width: `${overall}%` }} />
      </div>

      {topics.map((topic) => {
        const sc = statusClass(topic.confidence_score);
        return (
          <div className="topic-item" key={topic.id}>
            <div className="topic-row">
              <span className="topic-name">
                <span className={`status-dot ${sc}`} />
                {topic.name}
              </span>
              <span className="topic-score">{topic.confidence_score}%</span>
            </div>
            <div className="topic-bar-outer">
              <div
                className={`topic-bar-inner ${sc}`}
                style={{ width: `${topic.confidence_score}%` }}
              />
            </div>
            {topic.missing_sections?.length > 0 && topic.confidence_score < KT_THRESHOLD && (
              <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: 2 }}>
                Missing: {topic.missing_sections.slice(0, 3).join(', ')}
                {topic.missing_sections.length > 3 ? ` +${topic.missing_sections.length - 3}` : ''}
              </div>
            )}
          </div>
        );
      })}

      <p
        style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 14, textAlign: 'center', paddingTop: 10, borderTop: '1px solid var(--border-subtle)' }}
      >
        Recommended coverage: {KT_THRESHOLD}% per topic
      </p>
    </div>
  );
}
