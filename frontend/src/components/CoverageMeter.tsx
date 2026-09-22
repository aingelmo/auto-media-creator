import { formatSecs } from "./mediaMeta";

/** Live readiness strip for the Media step: footage vs. track length. */
export default function CoverageMeter({
  clipCount,
  clipSecs,
  musicName,
  musicSecs,
}: {
  clipCount: number;
  clipSecs: number;
  musicName: string;
  musicSecs: number | null;
}) {
  if (clipCount === 0 && !musicName) {
    return (
      <p className="coverage-meter status-pending">
        Pick clips and a music track to check coverage.
      </p>
    );
  }
  if (clipCount === 0) {
    return <p className="coverage-meter status-failed">No clips yet — pick or drop some.</p>;
  }
  if (!musicName) {
    return (
      <p className="coverage-meter status-failed">
        {clipCount} clips (~{formatSecs(clipSecs)} footage) — still need a music track.
      </p>
    );
  }
  if (musicSecs == null) {
    return (
      <p className="coverage-meter status-pending">
        {clipCount} clips (~{formatSecs(clipSecs)} footage) · track {musicName} (length unknown) —
        coverage check needs the track length.
      </p>
    );
  }
  if (clipSecs >= musicSecs) {
    return (
      <p className="coverage-meter status-running">
        Ready: ~{formatSecs(clipSecs)} footage covers the {formatSecs(musicSecs)} track.
      </p>
    );
  }
  return (
    <p className="coverage-meter status-failed">
      Thin: ~{formatSecs(clipSecs)} footage for a {formatSecs(musicSecs)} track — add more clips or
      pick a shorter track.
    </p>
  );
}
