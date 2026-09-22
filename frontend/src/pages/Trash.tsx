import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";
import { useConfirm } from "../components/confirm";
import { formatAge, formatSize } from "../components/mediaMeta";
import {
  listClientTrash,
  notifyTrashChanged,
  purgeClientItem,
  restorePreset,
  type ClientTrashItem,
} from "../trash";
import type { TrashItem, TrashPayload } from "../types";

type RowKind = "session" | "media" | "preset";

interface Row {
  id: string;
  kind: RowKind;
  label: string;
  origin: string;
  detail: string;
  sizeBytes: number | null;
  deletedAt: number;
  purgeAfter: number;
}

const GROUPS: { kind: RowKind; title: string }[] = [
  { kind: "session", title: "Sessions" },
  { kind: "media", title: "Media" },
  { kind: "preset", title: "Brand presets" },
];

function numberMeta(meta: Record<string, unknown>, key: string): number | null {
  const value = meta[key];
  return typeof value === "number" ? value : null;
}

function stringMeta(meta: Record<string, unknown>, key: string): string | null {
  const value = meta[key];
  return typeof value === "string" && value ? value : null;
}

function serverRow(item: TrashItem): Row {
  if (item.kind === "session") {
    const clips = numberMeta(item.meta, "clip_count");
    const detail = [
      stringMeta(item.meta, "status"),
      clips != null ? `${clips} clip${clips === 1 ? "" : "s"}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    return {
      id: item.id,
      kind: "session",
      label: item.label,
      origin: "sessions/",
      detail,
      sizeBytes: item.size_bytes,
      deletedAt: item.deleted_at,
      purgeAfter: item.purge_after,
    };
  }
  return {
    id: item.id,
    kind: "media",
    label: item.label,
    origin: item.session,
    detail: item.origin,
    sizeBytes: item.size_bytes,
    deletedAt: item.deleted_at,
    purgeAfter: item.purge_after,
  };
}

function presetRow(item: ClientTrashItem): Row {
  return {
    id: item.id,
    kind: "preset",
    label: item.label,
    origin: "browser",
    detail: "brand preset",
    sizeBytes: null,
    deletedAt: item.deletedAt,
    purgeAfter: item.purgeAfter,
  };
}

function daysLeft(purgeAfter: number): number {
  return Math.max(0, Math.ceil((purgeAfter - Date.now()) / 86_400_000));
}

export default function Trash() {
  const [data, setData] = useState<TrashPayload | null>(null);
  const [presets, setPresets] = useState<ClientTrashItem[]>(() => listClientTrash());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const confirm = useConfirm();

  const load = useCallback(async () => {
    const payload = await api.getTrash();
    setData(payload);
    setPresets(listClientTrash());
  }, []);

  useEffect(() => {
    load().catch((err) =>
      setError(err instanceof ApiError ? err.detail : "Could not load the trash."),
    );
  }, [load]);

  function fail(err: unknown, fallback: string) {
    setError(err instanceof ApiError ? err.detail : fallback);
  }

  async function handleRestore(row: Row) {
    setBusy(row.id);
    setError(null);
    try {
      if (row.kind === "preset") restorePreset(row.id);
      else await api.restoreTrashItem(row.id);
      notifyTrashChanged();
      await load();
    } catch (err) {
      fail(err, `Could not restore ${row.label}.`);
    } finally {
      setBusy(null);
    }
  }

  async function handlePurge(row: Row) {
    const ok = await confirm({
      title: `Delete ${row.label} forever?`,
      body: (
        <>
          <p>Permanently removes it from disk. Nothing can bring it back.</p>
          <p className="confirm-note is-fail">This cannot be undone.</p>
        </>
      ),
      confirmLabel: "Delete forever",
      tone: "danger",
      requireText: row.kind === "session" ? row.label : undefined,
    });
    if (!ok) return;
    setBusy(row.id);
    setError(null);
    try {
      if (row.kind === "preset") purgeClientItem(row.id);
      else await api.purgeTrashItem(row.id);
      notifyTrashChanged();
      await load();
    } catch (err) {
      fail(err, `Could not delete ${row.label}.`);
    } finally {
      setBusy(null);
    }
  }

  async function handleEmpty() {
    const ok = await confirm({
      title: "Empty the trash?",
      body: (
        <>
          <p>Permanently deletes every item in the bin. Nothing can bring them back.</p>
          <p className="confirm-note is-fail">This cannot be undone.</p>
        </>
      ),
      confirmLabel: "Empty trash",
      tone: "danger",
      requireText: "EMPTY",
    });
    if (!ok) return;
    setBusy("*");
    setError(null);
    try {
      await api.emptyTrash();
      for (const item of listClientTrash()) purgeClientItem(item.id);
      notifyTrashChanged();
      await load();
    } catch (err) {
      fail(err, "Could not empty the trash.");
    } finally {
      setBusy(null);
    }
  }

  const rows: Row[] = data
    ? [...data.items.map(serverRow), ...presets.map(presetRow)]
    : presets.map(presetRow);
  const totalBytes = rows.reduce((sum, row) => sum + (row.sizeBytes ?? 0), 0);
  const nextPurge = rows.length ? Math.min(...rows.map((row) => row.purgeAfter)) : null;

  return (
    <>
      <h2>Trash</h2>
      <p className="trash-summary">
        {data === null && rows.length === 0 ? (
          "Loading…"
        ) : rows.length === 0 ? (
          <>
            Nothing here. Deleted sessions and clips land in the bin for{" "}
            {data?.retention_days ?? 30} days.
          </>
        ) : (
          <>
            {rows.length} item{rows.length === 1 ? "" : "s"} · {formatSize(totalBytes)} · next purge
            in {daysLeft(nextPurge ?? 0)}d · items older than {data?.retention_days ?? 30} days
            delete themselves
          </>
        )}
      </p>

      {error && (
        <p className="status-failed" role="alert">
          {error}
        </p>
      )}

      {rows.length === 0 && data !== null && (
        <p className="trash-empty">
          <Link to="/">Back to the bench</Link>
        </p>
      )}

      {GROUPS.map(({ kind, title }) => {
        const groupRows = rows.filter((row) => row.kind === kind);
        if (groupRows.length === 0) return null;
        return (
          <section key={kind} className="trash-group" aria-label={title}>
            <h3>{title}</h3>
            <div className="table-scroll">
              <table className="trash-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Origin</th>
                    <th className="num">Size</th>
                    <th>Deleted</th>
                    <th className="num">Purges</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {groupRows.map((row) => {
                    const days = daysLeft(row.purgeAfter);
                    return (
                      <tr key={row.id}>
                        <td>
                          <span className="trash-label">{row.label}</span>
                          {row.detail && <span className="trash-item-detail">{row.detail}</span>}
                        </td>
                        <td className="trash-origin">{row.origin}</td>
                        <td className="num">
                          {row.sizeBytes === null ? "—" : formatSize(row.sizeBytes)}
                        </td>
                        <td>{formatAge(row.deletedAt / 1000)}</td>
                        <td className={`num trash-purge${days <= 3 ? " is-soon" : ""}`}>
                          {days === 0 ? "today" : `${days}d`}
                        </td>
                        <td className="trash-actions">
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => void handleRestore(row)}
                            disabled={busy !== null}
                          >
                            {busy === row.id ? "Working…" : "Restore"}
                          </button>
                          <button
                            type="button"
                            className="danger-text"
                            onClick={() => void handlePurge(row)}
                            disabled={busy !== null}
                          >
                            Delete forever
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      {rows.length > 0 && (
        <p className="trash-foot">
          <button
            type="button"
            className="danger"
            onClick={() => void handleEmpty()}
            disabled={busy !== null}
          >
            {busy === "*" ? "Emptying…" : `Empty trash (${rows.length})`}
          </button>
        </p>
      )}
    </>
  );
}
