"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "../lib/useSSE";
import { AssistantText, UserMessage } from "../components/Message";
import { ToolActivity } from "../components/ToolActivity";
import { ComponentCard } from "../components/ComponentCard";

const SUGGESTIONS = [
  "How do I install part PS11752778?",
  "My dishwasher isn't draining — what part do I need?",
  "Is PS11752778 compatible with WDT780SAEM1?",
  "What parts are available for model WDT780SAEM1?",
];

export default function Page() {
  const { messages, streaming, send } = useChat();
  const [input, setInput] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const submit = (text: string) => {
    const t = text.trim();
    if (!t || streaming) return;
    send(t);
    setInput("");
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit(input);
  };

  return (
    <main className="ps-page">
      <div className="ps-chat">
        <div className="ps-chat__head">
          <h1>PartSelect Assistant</h1>
          <p>Refrigerator &amp; Dishwasher parts, compatibility, and repair help</p>
        </div>

        <div className="ps-chat__body" ref={bodyRef}>
          {messages.length === 0 && (
            <div className="ps-empty">
              <h2>How can I help with your repair?</h2>
              <p>
                Ask about a specific part number, describe a symptom, or check whether a part fits
                your model.
              </p>
              <div className="ps-suggest">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => submit(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => {
            if (m.role === "user") {
              return <UserMessage key={i} content={m.content} />;
            }
            const isLast = i === messages.length - 1;
            const waiting =
              streaming &&
              isLast &&
              m.content === "" &&
              m.tools.length === 0 &&
              m.components.length === 0;
            return (
              <div className="ps-turn" key={i}>
                <ToolActivity tools={m.tools} />
                {m.components.length > 0 && (
                  <div className="ps-cards">
                    {m.components.map((c, j) => (
                      <ComponentCard key={j} item={c} />
                    ))}
                  </div>
                )}
                {waiting && (
                  <div className="ps-activity">
                    <div className="ps-typing" aria-label="Assistant is thinking">
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>
                )}
                <AssistantText content={m.content} />
                {m.error && (
                  <div className="ps-bubble ps-bubble--assistant" style={{ color: "var(--ps-red)" }}>
                    Something went wrong: {m.error}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <form className="ps-composer" onSubmit={onSubmit}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a part, symptom, or model…"
          />
          <button type="submit" disabled={streaming || !input.trim()}>
            {streaming ? "…" : "Send"}
          </button>
        </form>
      </div>
    </main>
  );
}
