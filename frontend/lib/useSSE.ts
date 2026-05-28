"use client";

import { useCallback, useState } from "react";

export type ComponentKind =
  | "product_card"
  | "install_steps"
  | "compatibility"
  | "model_info"
  | "symptom_parts"
  | "qa_results"
  | "escalation";

export type ComponentItem = { kind: ComponentKind; data: Record<string, unknown> };

export type ToolActivity = { name: string; status: "running" | "done" };

export type UserTurn = { role: "user"; content: string };
export type AssistantTurn = {
  role: "assistant";
  content: string;
  tools: ToolActivity[];
  components: ComponentItem[];
  error?: string;
};
export type Turn = UserTurn | AssistantTurn;

type SSEEvent =
  | { type: "token"; delta: string }
  | { type: "tool_start"; name: string; args: Record<string, unknown> }
  | { type: "component"; kind: ComponentKind; data: Record<string, unknown> }
  | { type: "done" }
  | { type: "error"; message: string };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// SSE-over-POST client. Each assistant turn accumulates streamed prose plus the
// tool activity and rich component cards the agent emits, so the UI can render
// them interleaved with the conversation.
export function useChat() {
  const [messages, setMessages] = useState<Turn[]>([]);
  const [streaming, setStreaming] = useState(false);

  const updateLast = useCallback(
    (fn: (turn: AssistantTurn) => AssistantTurn) => {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "assistant") {
          next[next.length - 1] = fn(last);
        }
        return next;
      });
    },
    []
  );

  const send = useCallback(
    async (text: string) => {
      const priorHistory = messages.map((m) => ({ role: m.role, content: m.content }));
      const history = [...priorHistory, { role: "user" as const, content: text }];

      setMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: "", tools: [], components: [] },
      ]);
      setStreaming(true);

      const finishTools = (turn: AssistantTurn): ToolActivity[] =>
        turn.tools.map((t) => ({ ...t, status: "done" as const }));

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: history }),
        });
        if (!res.ok || !res.body) {
          throw new Error(`Request failed (${res.status})`);
        }

        const reader = res.body.getReader();
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
            let evt: SSEEvent;
            try {
              evt = JSON.parse(line);
            } catch {
              continue;
            }

            if (evt.type === "token") {
              updateLast((turn) => ({
                ...turn,
                content: turn.content + evt.delta,
                tools: finishTools(turn),
              }));
            } else if (evt.type === "tool_start") {
              updateLast((turn) => ({
                ...turn,
                tools: [...turn.tools, { name: evt.name, status: "running" }],
              }));
            } else if (evt.type === "component") {
              updateLast((turn) => ({
                ...turn,
                tools: finishTools(turn),
                components: [...turn.components, { kind: evt.kind, data: evt.data }],
              }));
            } else if (evt.type === "error") {
              updateLast((turn) => ({
                ...turn,
                tools: finishTools(turn),
                error: evt.message,
              }));
            } else if (evt.type === "done") {
              updateLast((turn) => ({ ...turn, tools: finishTools(turn) }));
            }
          }
        }
      } catch (err) {
        updateLast((turn) => ({
          ...turn,
          tools: turn.tools.map((t) => ({ ...t, status: "done" as const })),
          error: err instanceof Error ? err.message : "Connection error",
        }));
      } finally {
        setStreaming(false);
      }
    },
    [messages, updateLast]
  );

  const reset = useCallback(() => {
    setMessages([]);
    setStreaming(false);
  }, []);

  return { messages, streaming, send, reset };
}
