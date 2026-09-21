import { useState } from "react";
import { PERSONALITY_FIELDS } from "./prefs";
import { Panel, SetRow } from "./ui";

export function PersonalitySettings({ draft, save }: {
  draft: Record<string, unknown>;
  save: (body: Record<string, unknown>, message?: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pick = async (key: string, value: string) => {
    setBusy(true);
    setError("");
    try {
      await save({ [key]: value }, "Personality saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save personality");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel icon="chat" title="Conversational personality" sub="Applies to local and permitted cloud chat models">
      {PERSONALITY_FIELDS.map((field) => (
        <SetRow key={field.key} title={field.label} control={
          <select aria-label={field.label} disabled={busy}
            value={String(draft[field.key] ?? field.fallback)}
            onChange={(e) => void pick(field.key, e.target.value)}>
            {field.options.map((option) => <option key={option} value={option}>{option[0].toUpperCase() + option.slice(1)}</option>)}
          </select>
        } />
      ))}
      <small className="dim">Delivery preferences, not feelings or consciousness. Facts, verified actions, approval rules and privacy stay unchanged. Pacing shapes replies; speech rate controls audio speed. Built-in fallback replies remain deterministic.</small>
      {error && <p role="alert">{error}</p>}
    </Panel>
  );
}
