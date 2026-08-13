const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

/**
 * Posts a question to /chat. Pass the running conversationId (or
 * undefined on the first message) -- the backend mints one and returns
 * it, and every subsequent call should echo it back so multi-turn
 * follow-ups resolve against the same server-side history.
 */
export async function sendChatMessage(question, conversationId) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      conversation_id: conversationId || null,
    }),
  });

  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON -- keep the generic message
    }
    throw new Error(detail);
  }

  return res.json();
}

export async function resetConversation(conversationId) {
  if (!conversationId) return;
  await fetch(`${API_BASE}/chat/reset/${conversationId}`, { method: "POST" });
}
