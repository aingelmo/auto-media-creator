/** Actionable job-failure card: headline + recovery message, trace collapsed. */
function splitJobError(raw: string): { kind: string | null; message: string } {
  const lines = raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const last = lines.length > 0 ? lines[lines.length - 1] : raw.trim();
  const sep = last.indexOf(": ");
  if (sep > 0 && sep <= 80) {
    const kindPath = last.slice(0, sep);
    const kind = kindPath.split(".").pop() ?? kindPath;
    return { kind, message: last.slice(sep + 2) };
  }
  return { kind: null, message: last };
}

export default function JobError({ error, title }: { error: string; title?: string }) {
  const { kind, message } = splitJobError(error);
  const headline =
    title ?? (kind?.toLowerCase().includes("planner") ? "Planning failed" : "Render failed");
  const multiline = error.trim().includes("\n");
  return (
    <div className="job-error" role="alert">
      <p className="job-error-title status-failed">{headline}</p>
      <p className="job-error-message">{message}</p>
      {kind && <p className="job-error-kind">{kind}</p>}
      {multiline && (
        <details className="job-error-details">
          <summary>Technical details</summary>
          <pre>{error}</pre>
        </details>
      )}
    </div>
  );
}
