import type { ComponentItem } from "../lib/useSSE";

/* ---------- shared types & helpers ---------- */

type Part = {
  ps_number?: string;
  mfg_part_number?: string;
  name?: string;
  brand?: string;
  appliance_type?: string;
  price?: number | string | null;
  stock_status?: string | null;
  description?: string | null;
  image_url?: string | null;
  url?: string | null;
  symptoms?: string[];
  effectiveness?: number | string | null;
};

function fmtPrice(price: Part["price"]): string | null {
  if (price === null || price === undefined || price === "") return null;
  const n = typeof price === "string" ? parseFloat(price) : price;
  if (Number.isNaN(n)) return String(price);
  return `$${n.toFixed(2)}`;
}

function isInStock(status?: string | null): boolean {
  return !!status && /in ?stock|available/i.test(status);
}

function StockBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  const ok = isInStock(status);
  return <span className={`ps-badge ${ok ? "ps-badge--in" : "ps-badge--out"}`}>{status}</span>;
}

/* ---------- part card (reused widely) ---------- */

function PartCard({ part }: { part: Part }) {
  const price = fmtPrice(part.price);
  return (
    <div className="ps-part">
      {part.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="ps-part__img" src={part.image_url} alt={part.name ?? "part"} />
      ) : (
        <div className="ps-part__img ps-part__img--ph" aria-hidden>
          ⚙
        </div>
      )}
      <div className="ps-part__body">
        <p className="ps-part__name">{part.name ?? "Part"}</p>
        <div className="ps-part__meta">
          {part.ps_number && (
            <span>
              PS#: <b>{part.ps_number}</b>
            </span>
          )}
          {part.mfg_part_number && (
            <span>
              Mfg#: <b>{part.mfg_part_number}</b>
            </span>
          )}
          {part.brand && (
            <span>
              Brand: <b>{part.brand}</b>
            </span>
          )}
        </div>
        {part.symptoms && part.symptoms.length > 0 && (
          <div className="ps-chips" style={{ marginBottom: 6 }}>
            {part.symptoms.slice(0, 4).map((s, i) => (
              <span className="ps-badge ps-badge--chip" key={i}>
                {s}
              </span>
            ))}
          </div>
        )}
        <div className="ps-part__foot">
          {price && <span className="ps-price">{price}</span>}
          <StockBadge status={part.stock_status} />
          {part.url && (
            <a className="ps-link" href={part.url} target="_blank" rel="noopener noreferrer">
              View on PartSelect
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function CardShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="ps-card">
      <div className="ps-card__title">{title}</div>
      {children}
    </div>
  );
}

function NotFound({ what }: { what: string }) {
  return (
    <CardShell title="No match">
      <div className="ps-card__pad" style={{ color: "var(--ps-muted)" }}>
        Couldn&apos;t find {what}. Double-check the number, or describe your model and symptom.
      </div>
    </CardShell>
  );
}

/* ---------- per-kind renderers ---------- */

function ProductCard({ data }: { data: Record<string, unknown> }) {
  if (data.found === false) {
    return <NotFound what={`part “${data.sku ?? ""}”`} />;
  }
  const parts: Part[] = Array.isArray(data.parts)
    ? (data.parts as Part[])
    : data.part
      ? [data.part as Part]
      : [];
  if (parts.length === 0) return <NotFound what="any matching parts" />;
  const title =
    parts.length > 1 ? `${parts.length} matching parts` : "Part";
  return (
    <CardShell title={title}>
      {parts.map((p, i) => (
        <PartCard part={p} key={i} />
      ))}
    </CardShell>
  );
}

function InstallSteps({ data }: { data: Record<string, unknown> }) {
  if (data.found === false) return <NotFound what="that part" />;
  const part = (data.part ?? {}) as Part;
  const steps = (data.install_steps as string[]) ?? [];
  const symptoms = (data.symptoms as { name: string; effectiveness?: number | string }[]) ?? [];
  const qa = (data.qa as { question: string; answer: string }[]) ?? [];
  return (
    <CardShell title={`Installation — ${part.name ?? part.ps_number ?? "part"}`}>
      <PartCard part={part} />
      <div className="ps-card__pad" style={{ paddingTop: 0 }}>
        {steps.length > 0 ? (
          <>
            <div className="ps-section-h">Installation steps</div>
            <ol className="ps-steps">
              {steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </>
        ) : (
          <p style={{ color: "var(--ps-muted)" }}>No installation steps recorded for this part.</p>
        )}
        {symptoms.length > 0 && (
          <>
            <div className="ps-section-h">Fixes these symptoms</div>
            <div className="ps-chips">
              {symptoms.map((s, i) => (
                <span className="ps-badge ps-badge--chip" key={i}>
                  {s.name}
                  {s.effectiveness ? ` · ${s.effectiveness}` : ""}
                </span>
              ))}
            </div>
          </>
        )}
        {qa.length > 0 && (
          <>
            <div className="ps-section-h">Related Q&amp;A</div>
            {qa.slice(0, 4).map((q, i) => (
              <div className="ps-qa" key={i}>
                <div className="ps-qa__q">{q.question}</div>
                <div className="ps-qa__a">{q.answer}</div>
              </div>
            ))}
          </>
        )}
      </div>
    </CardShell>
  );
}

function ModelInfo({ data }: { data: Record<string, unknown> }) {
  if (data.found === false) return <NotFound what={`model “${data.model_number ?? ""}”`} />;
  const model = (data.model ?? {}) as {
    model_number?: string;
    brand?: string;
    appliance_type?: string;
    name?: string;
    url?: string;
  };
  return (
    <CardShell title="Model">
      <div className="ps-card__pad">
        <div className="ps-kv">
          <b>Model</b>
          <span>{model.model_number}</span>
        </div>
        {model.name && (
          <div className="ps-kv">
            <b>Name</b>
            <span>{model.name}</span>
          </div>
        )}
        {model.brand && (
          <div className="ps-kv">
            <b>Brand</b>
            <span>{model.brand}</span>
          </div>
        )}
        {model.appliance_type && (
          <div className="ps-kv">
            <b>Appliance</b>
            <span>{model.appliance_type}</span>
          </div>
        )}
        <div className="ps-kv">
          <b>Compatible parts</b>
          <span>{String(data.compatible_part_count ?? 0)}</span>
        </div>
        {model.url && (
          <a className="ps-link" href={model.url} target="_blank" rel="noopener noreferrer">
            View on PartSelect
          </a>
        )}
      </div>
    </CardShell>
  );
}

function Compatibility({ data }: { data: Record<string, unknown> }) {
  const compatible = data.compatible as boolean | null;
  const psNumber = data.ps_number as string | undefined;
  const partName = data.part_name as string | undefined;
  const modelNumber = data.model_number as string | undefined;
  const modelName = data.model_name as string | undefined;

  let cls = "ps-banner--unknown";
  let icon = "?";
  let text = "Compatibility unknown";
  if (compatible === true) {
    cls = "ps-banner--yes";
    icon = "✓";
    text = "Compatible";
  } else if (compatible === false) {
    cls = "ps-banner--no";
    icon = "✕";
    text = "Not compatible";
  }

  return (
    <CardShell title="Compatibility check">
      <div className={`ps-banner ${cls}`}>
        <span className="ps-banner__icon" aria-hidden>
          {icon}
        </span>
        <span>{text}</span>
      </div>
      <div className="ps-card__pad" style={{ paddingTop: 12 }}>
        {(psNumber || partName) && (
          <div className="ps-kv">
            <b>Part</b>
            <span>
              {partName}
              {psNumber ? ` (${psNumber})` : ""}
            </span>
          </div>
        )}
        {(modelNumber || modelName) && (
          <div className="ps-kv">
            <b>Model</b>
            <span>
              {modelNumber}
              {modelName ? ` — ${modelName}` : ""}
            </span>
          </div>
        )}
        {compatible === null && data.reason === "part_not_found" && (
          <p style={{ color: "var(--ps-muted)" }}>That part number wasn&apos;t found.</p>
        )}
        {compatible === null && data.reason === "model_not_found" && (
          <p style={{ color: "var(--ps-muted)" }}>That model number wasn&apos;t found.</p>
        )}
      </div>
    </CardShell>
  );
}

function SymptomParts({ data }: { data: Record<string, unknown> }) {
  if (data.found === false) return <NotFound what={`model “${data.model_number ?? ""}”`} />;
  const groups =
    (data.symptoms as { symptom: string; parts: Part[] }[]) ?? [];
  if (groups.length === 0) {
    return (
      <CardShell title="Symptom matches">
        <div className="ps-card__pad" style={{ color: "var(--ps-muted)" }}>
          No matching symptoms recorded for this model.
        </div>
      </CardShell>
    );
  }
  return (
    <CardShell title={`Symptom matches — ${data.model_number ?? ""}`}>
      <div className="ps-card__pad">
        {groups.map((g, i) => (
          <div key={i} style={{ marginBottom: i < groups.length - 1 ? 14 : 0 }}>
            <div className="ps-section-h" style={{ marginTop: i === 0 ? 0 : 12 }}>
              {g.symptom}
            </div>
            {g.parts.map((p, j) => (
              <div className="ps-kv" key={j}>
                <b>{p.name}</b>
                <span>
                  {p.ps_number}
                  {fmtPrice(p.price) ? ` · ${fmtPrice(p.price)}` : ""}
                  {p.effectiveness ? ` · fixes ${p.effectiveness}` : ""}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </CardShell>
  );
}

function QaResults({ data }: { data: Record<string, unknown> }) {
  if (data.found === false) return <NotFound what={`model “${data.model_number ?? ""}”`} />;
  const results = (data.results as { question: string; answer: string }[]) ?? [];
  if (results.length === 0) {
    return (
      <CardShell title="Q&A">
        <div className="ps-card__pad" style={{ color: "var(--ps-muted)" }}>
          No related questions found for this model.
        </div>
      </CardShell>
    );
  }
  return (
    <CardShell title={`Q&A — ${data.model_number ?? ""}`}>
      <div className="ps-card__pad">
        {results.map((q, i) => (
          <div className="ps-qa" key={i} style={{ borderTop: i === 0 ? "none" : undefined, paddingTop: i === 0 ? 0 : undefined, marginTop: i === 0 ? 0 : undefined }}>
            <div className="ps-qa__q">{q.question}</div>
            <div className="ps-qa__a">{q.answer}</div>
          </div>
        ))}
      </div>
    </CardShell>
  );
}

function Escalation({ data }: { data: Record<string, unknown> }) {
  return (
    <CardShell title="Support">
      <div className="ps-banner ps-banner--escalate">
        <span className="ps-banner__icon" aria-hidden>
          🎧
        </span>
        <span>{(data.message as string) ?? "Connecting you with a PartSelect specialist."}</span>
      </div>
    </CardShell>
  );
}

/* ---------- dispatcher ---------- */

export function ComponentCard({ item }: { item: ComponentItem }) {
  switch (item.kind) {
    case "product_card":
      return <ProductCard data={item.data} />;
    case "install_steps":
      return <InstallSteps data={item.data} />;
    case "model_info":
      return <ModelInfo data={item.data} />;
    case "compatibility":
      return <Compatibility data={item.data} />;
    case "symptom_parts":
      return <SymptomParts data={item.data} />;
    case "qa_results":
      return <QaResults data={item.data} />;
    case "escalation":
      return <Escalation data={item.data} />;
    default:
      return null;
  }
}
