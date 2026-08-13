"use client";

import { useEffect, useRef, useState } from "react";
import { AssistantMessage, PendingMessage, UserMessage } from "../components/ChatMessage";
import { resetConversation, sendChatMessage } from "../lib/api";

const SAMPLE_QUESTIONS = [
  "What was transaction volume last quarter by state?",
  "Which bank settles the most merchant transactions?",
  "Show me the success rate of UPI payments versus card payments",
];

export default function Page() {
  const [messages, setMessages] = useState([]); // { role: 'user'|'assistant', text?, result? }
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState(null);
  const [pending, setPending] = useState(false);
  const [connError, setConnError] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, pending]);

  async function submit(question) {
    const q = question.trim();
    if (!q || pending) return;

    setConnError(null);
    setMessages((m) => [...m, { role: "user", text: q }]);
    setInput("");
    setPending(true);

    try {
      const result = await sendChatMessage(q, conversationId);
      setConversationId(result.conversation_id);
      setMessages((m) => [...m, { role: "assistant", result }]);
    } catch (err) {
      setConnError(
        err.message?.includes("fetch") || err.message?.includes("Failed")
          ? "Can't reach the QueryMind backend — is it running at localhost:8000?"
          : err.message
      );
      setMessages((m) => m.slice(0, -1)); // drop the optimistic user bubble, nothing answered it
    } finally {
      setPending(false);
    }
  }

  async function handleNewChat() {
    if (conversationId) await resetConversation(conversationId);
    setConversationId(null);
    setMessages([]);
    setConnError(null);
  }

  return (
    <main className="flex h-screen flex-col bg-ink-900">
      <header className="flex items-center justify-between border-b border-ink-600 bg-ink-800/60 px-6 py-4">
        <div>
          <h1 className="font-mono text-lg tracking-tight text-parchment-100">
            Query<span className="text-ledger-gold">Mind</span>
          </h1>
          <p className="text-xs text-parchment-300/60">Ask your ledger, in plain English</p>
        </div>
        <button
          onClick={handleNewChat}
          className="rounded-md border border-ink-600 px-3 py-1.5 text-xs text-parchment-300/80 hover:border-ledger-gold hover:text-ledger-gold"
        >
          New chat
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.length === 0 && (
            <div className="mt-10 text-center">
              <p className="text-sm text-parchment-300/60">
                Try one of these, or ask your own question about the payments dataset.
              </p>
              <div className="mt-4 flex flex-col gap-2">
                {SAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => submit(q)}
                    className="rounded-lg border border-ink-600 bg-ink-800/40 px-4 py-2 text-left text-sm text-parchment-100 hover:border-ledger-gold/50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? <UserMessage key={i} text={m.text} /> : <AssistantMessage key={i} result={m.result} />
          )}

          {pending && <PendingMessage />}

          {connError && (
            <div className="rounded-lg border border-ledger-clay/40 bg-ledger-clay/10 px-4 py-2.5 text-sm text-ledger-clay">
              {connError}
            </div>
          )}
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(input);
        }}
        className="border-t border-ink-600 bg-ink-800/60 px-6 py-4"
      >
        <div className="mx-auto flex max-w-3xl gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about transactions, merchants, disputes..."
            className="flex-1 rounded-lg border border-ink-600 bg-ink-900 px-4 py-2.5 text-sm text-parchment-100 placeholder:text-parchment-300/40 focus:border-ledger-gold"
            disabled={pending}
          />
          <button
            type="submit"
            disabled={pending || !input.trim()}
            className="rounded-lg bg-ledger-gold px-5 py-2.5 text-sm font-medium text-ink-900 disabled:opacity-40"
          >
            Ask
          </button>
        </div>
      </form>
    </main>
  );
}
