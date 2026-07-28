const BASE_URL = '';

// ─── User Identity ────────────────────────────────────────────────────────────
// Auto-generate a persistent user ID stored in localStorage.
// This ensures each browser has its own isolated session history.

function generateUUID() {
  // crypto.randomUUID() requires HTTPS/localhost (secure context).
  // crypto.getRandomValues() works everywhere including LAN IPs over HTTP.
  return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}

function getUserId() {
  let userId = localStorage.getItem('kt_user_id');
  if (!userId) {
    userId = generateUUID();
    localStorage.setItem('kt_user_id', userId);
  }
  return userId;
}

// Central helper: builds base headers including the user identity token.
function baseHeaders(extra = {}) {
  return {
    'X-User-Id': getUserId(),
    ...extra,
  };
}

// ─── Sessions ────────────────────────────────────────────────────────────────

export async function getSessions() {
  const res = await fetch(`${BASE_URL}/api/sessions`, {
    headers: baseHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`);
  return res.json();
}

export async function createSession() {
  const res = await fetch(`${BASE_URL}/api/sessions`, {
    method: 'POST',
    headers: baseHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function getSession(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
    headers: baseHeaders(),
  });
  if (!res.ok) throw new Error(`Session not found: ${res.status}`);
  return res.json();
}

export async function getMessages(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/messages`, {
    headers: baseHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`);
  return res.json();
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: baseHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`);
  return res.json();
}

// ─── Ingest ──────────────────────────────────────────────────────────────────

export async function getBranches(sessionId, url) {
  const params = new URLSearchParams({ url });
  const res = await fetch(
    `${BASE_URL}/api/sessions/${sessionId}/ingest/branches?${params}`,
    { headers: baseHeaders() }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Failed to fetch branches: ${res.status}`);
  }
  return res.json();
}

/**
 * Ingests a GitHub repo via SSE stream.
 * onEvent(event) is called for each SSE message.
 */
export function ingestGithub(sessionId, githubUrl, branch, onEvent, signal) {
  const body = JSON.stringify({ github_url: githubUrl, branch });
  return fetch(`${BASE_URL}/api/sessions/${sessionId}/ingest/github`, {
    method: 'POST',
    headers: baseHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
    body,
    signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Ingest failed: ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop(); // keep partial
      for (const block of lines) {
        const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
        if (dataLine) {
          try {
            const event = JSON.parse(dataLine.slice(6));
            onEvent(event);
          } catch {}
        }
      }
    }
  });
}

export function ingestFile(sessionId, file, onEvent, signal) {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${BASE_URL}/api/sessions/${sessionId}/ingest/file`, {
    method: 'POST',
    headers: baseHeaders({ Accept: 'text/event-stream' }), // Do NOT set Content-Type for FormData
    body: form,
    signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `File ingest failed: ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop(); // keep partial
      for (const block of lines) {
        const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
        if (dataLine) {
          try {
            const event = JSON.parse(dataLine.slice(6));
            onEvent(event);
          } catch {}
        }
      }
    }
  });
}

// ─── Chat ────────────────────────────────────────────────────────────────────

/**
 * Sends a chat question via SSE stream.
 * onEvent(event) is called for each SSE message.
 */
export function sendChatMessage(sessionId, question, onEvent, signal) {
  const body = JSON.stringify({ question });
  return fetch(`${BASE_URL}/api/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: baseHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
    body,
    signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Chat failed: ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop();
      for (const block of lines) {
        const dataLine = block.split('\n').find((l) => l.startsWith('data: '));
        if (dataLine) {
          try {
            const event = JSON.parse(dataLine.slice(6));
            onEvent(event);
          } catch {}
        }
      }
    }
  });
}

// ─── Documents ───────────────────────────────────────────────────────────────

export async function generateDocument(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/document/generate`, {
    method: 'POST',
    headers: baseHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Generate failed: ${res.status}`);
  }
  return res.json();
}

export async function getDocument(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/document`, {
    headers: baseHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Document not found: ${res.status}`);
  }
  return res.json();
}

export function getPdfUrl(sessionId) {
  // Append user_id as query param since we can't set headers on <a href> links
  return `${BASE_URL}/api/sessions/${sessionId}/document/pdf?user_id=${getUserId()}`;
}

export function getDocxUrl(sessionId) {
  return `${BASE_URL}/api/sessions/${sessionId}/document/docx?user_id=${getUserId()}`;
}

export async function healthCheck() {
  const res = await fetch(`${BASE_URL}/health`);
  return res.ok;
}
