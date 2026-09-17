import type { HistoryEntry } from "../types";

/** One-line-per-entry summary of what a regen actually changed, e.g.
 * "selection · deepseek/deepseek-flash · theme=training". */
function summarize(entry: HistoryEntry): string {
  const parts: string[] = [];
  if (entry.hook_line) parts.push(`hook="${entry.hook_line}"`);
  else if (["candidates", "selection", "hooks"].includes(entry.from_stage)) {
    parts.push(`${entry.provider}/${entry.model}`, `theme=${entry.theme}`);
  }
  if (entry.brief) parts.push(`brief="${entry.brief}"`);
  if (entry.brand_updated) parts.push("brand updated");
  return parts.join(" · ");
}

export default function RegenHistory({ entries }: { entries: HistoryEntry[] }) {
  if (entries.length === 0) return null;

  return (
    <details className="regen-history">
      <summary>history ({entries.length})</summary>
      <table>
        <tbody>
          {entries.map((entry, i) => (
            <tr key={entry.ts}>
              <td className="num">{entries.length - i}</td>
              <td>{new Date(entry.ts).toLocaleString()}</td>
              <td>{entry.from_stage}</td>
              <td>{summarize(entry)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
