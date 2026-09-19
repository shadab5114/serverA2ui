/**
 * Variant card (P8): the chrome the explorer persona gets around a surface.
 *
 *   label      "Baseline · plan-tiles@1", "Variant 2", "Variant 2 · rev 3", "Generated"
 *   rationale  why this variant (or revision) was made
 *   sources    the guidelines it relies on
 *   changes    what its patch changed against its base (the patch itself on demand)
 *   flags      guideline conflicts: shown, not silently repaired (explorer policy "flag")
 *   missing    data the variant would need that no provider has yet
 *
 * Everything comes from `meta.card` on the CUSTOM a2ui event; a surface
 * without one (the assistant persona) renders bare, as before.
 */
import { useState, type ReactNode } from "react";

export interface Card {
  id?: string;
  kind: "baseline" | "variant" | "generated";
  label: string;
  base?: string;
  rev?: number;
  title?: string;
  rationale?: string;
  sources?: { id: string; title: string }[];
  changes?: string[];
  flags?: { ruleId: string; problem: string; fix: string; componentIds?: string[] }[];
  missingData?: { field: string; why?: string }[];
  patch?: unknown[];
}

export default function VariantCard({ card, children }: { card: Card; children: ReactNode }) {
  const [showPatch, setShowPatch] = useState(false);
  const flags = card.flags ?? [];
  const missing = card.missingData ?? [];
  const changes = card.changes ?? [];
  const sources = card.sources ?? [];
  return (
    <section className={`variant-card ${card.kind}${flags.length ? " flagged" : ""}`}>
      <header className="variant-head">
        <span className="variant-label">{card.label}</span>
        {card.title && card.kind !== "baseline" && <span className="variant-title">{card.title}</span>}
        {card.kind === "variant" && card.base && <span className="variant-base">on {card.base}</span>}
      </header>
      {card.rationale && <p className="variant-rationale">{card.rationale}</p>}

      <div className="surface">{children}</div>

      {flags.length > 0 && (
        <ul className="variant-flags">
          {flags.map((f, i) => (
            <li key={i}>
              <span className="variant-cite">{f.ruleId}</span> {f.problem}
              {f.fix && <span className="variant-fix"> Alternative: {f.fix}</span>}
            </li>
          ))}
        </ul>
      )}
      {missing.length > 0 && (
        <div className="variant-missing">
          Needs data no provider has yet:{" "}
          {missing.map((m, i) => (
            <span key={i}>
              {i > 0 && ", "}
              <code>{m.field}</code>
              {m.why && <span className="variant-why"> ({m.why})</span>}
            </span>
          ))}
        </div>
      )}
      {(changes.length > 0 || sources.length > 0) && (
        <footer className="variant-foot">
          {changes.length > 0 && (
            <div className="variant-changes">
              <span className="variant-key">{card.rev && card.rev > 1 ? `Rev ${card.rev} changed` : "Changed"}</span>
              <ul>
                {changes.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
              {card.patch && (
                <button className="variant-toggle" onClick={() => setShowPatch(!showPatch)} aria-expanded={showPatch}>
                  {showPatch ? "Hide patch" : "Show patch"}
                </button>
              )}
              {showPatch && <pre className="trace-json">{JSON.stringify(card.patch, null, 2)}</pre>}
            </div>
          )}
          {sources.length > 0 && (
            <div className="variant-sources">
              <span className="variant-key">Grounded in</span>
              {sources.map((s) => (
                <span key={s.id} className="variant-source">
                  <span className="variant-cite">{s.id}</span> {s.title}
                </span>
              ))}
            </div>
          )}
        </footer>
      )}
    </section>
  );
}
