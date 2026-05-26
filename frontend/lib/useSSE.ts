"use client";

import { useCallback, useState } from "react";

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type SSEEvent =
  | { type: "token"; delta: string }
  | { type: "tool_start"; name: string; args: Record<string, unknown> }
  | { type: "component"; kind: string; data: Record<string, unknown> }
  | { type: "done" }
  | { type: "error"; message: string };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Minimal SSE-over-POST client: streams the agent's tokens + component events.
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [components, setComponents] = useState<SSEEvent[]>([]);
  const [streaming, setStreaming] = useState(false);

  const send = useCallback(
    async (text: string) => {
      const history: ChatMessage[] = [...messages, { role: "user", content: text }];
      setMessages([...history, { role: "assistant", content: "" }]);
      setStreaming(true);

      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.replace(/^data: /, "").trim();
          if (!line) continue;
          const evt: SSEEvent = JSON.parse(line);
          if (evt.type === "token") {
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                role: "assistant",
                content: next[next.length - 1].content + evt.delta,
              };
              return next;
            });
          } else if (evt.type === "component") {
            setComponents((prev) => [...prev, evt]);
          }
        }
      }
      setStreaming(false);
    },
    [messages]
  );

  return { messages, components, streaming, send };
}
