"use client";

import { useState } from "react";
import { useChat } from "../lib/useSSE";

// Scaffold UI: proves SSE streaming end-to-end. Component events are shown as JSON
// for now; the rich PartSelect-themed cards / diagrams / step visualizer land in the
// follow-up PR (the SSE `component` contract is already in place).
export default function Page() {
  const { messages, components, streaming, send } = useChat();
  const [input, setInput] = useState("");

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || streaming) return;
    send(input.trim());
    setInput("");
  };

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: 24 }}>
      <header style={{ background: "var(--ps-blue)", color: "#fff", padding: "16px 20px", borderRadius: 8 }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>PartSelect Assistant</h1>
        <p style={{ margin: "4px 0 0", opacity: 0.85, fontSize: 14 }}>
          Refrigerator &amp; Dishwasher parts, compatibility, and repairs
        </p>
      </header>

      <section style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              background: m.role === "user" ? "var(--ps-blue)" : "#fff",
              color: m.role === "user" ? "#fff" : "#1a1a1a",
              border: "1px solid #dce4ef",
              borderRadius: 12,
              padding: "10px 14px",
              maxWidth: "80%",
              whiteSpace: "pre-wrap",
            }}
          >
            {m.content || (streaming ? "…" : "")}
          </div>
        ))}
      </section>

      {components.length > 0 && (
        <section style={{ marginTop: 16 }}>
          <h2 style={{ fontSize: 13, color: "#5a6b82" }}>Component events (scaffold)</h2>
          {components.map((c, i) => (
            <pre
              key={i}
              style={{ background: "#fff", border: "1px solid #dce4ef", borderRadius: 8, padding: 12, fontSize: 12, overflowX: "auto" }}
            >
              {JSON.stringify(c, null, 2)}
            </pre>
          ))}
        </section>
      )}

      <form onSubmit={onSubmit} style={{ marginTop: 16, display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. How do I install part PS11752778?"
          style={{ flex: 1, padding: "10px 12px", borderRadius: 8, border: "1px solid #c5d2e3" }}
        />
        <button
          type="submit"
          disabled={streaming}
          style={{ background: "var(--ps-blue)", color: "#fff", border: 0, borderRadius: 8, padding: "10px 18px", cursor: "pointer" }}
        >
          Send
        </button>
      </form>
    </main>
  );
}
