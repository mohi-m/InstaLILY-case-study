import type { ToolActivity as ToolActivityType } from "../lib/useSSE";

const TOOL_LABELS: Record<string, { running: string; done: string }> = {
  search_by_symptom: { running: "Searching parts by symptom…", done: "Searched parts" },
  get_part_detail: { running: "Getting part details…", done: "Got part details" },
  get_model_info: { running: "Looking up model…", done: "Looked up model" },
  list_parts_for_model: { running: "Finding parts for model…", done: "Found parts for model" },
  check_compatibility: { running: "Checking compatibility…", done: "Checked compatibility" },
  find_symptoms_for_model: { running: "Matching symptoms…", done: "Matched symptoms" },
  search_model_qa: { running: "Searching Q&A…", done: "Searched Q&A" },
  escalate_to_human: { running: "Connecting to support…", done: "Connected to support" },
};

function label(name: string, status: "running" | "done"): string {
  const entry = TOOL_LABELS[name];
  if (entry) return entry[status];
  return status === "running" ? `Running ${name}…` : name;
}

export function ToolActivity({ tools }: { tools: ToolActivityType[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="ps-activity" aria-live="polite">
      {tools.map((t, i) => (
        <div className="ps-activity__row" key={i}>
          {t.status === "running" ? (
            <span className="ps-spinner" aria-hidden />
          ) : (
            <span className="ps-check" aria-hidden>
              ✓
            </span>
          )}
          <span className={t.status === "running" ? "ps-activity__label" : undefined}>
            {label(t.name, t.status)}
          </span>
        </div>
      ))}
    </div>
  );
}
