import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Manifest } from "../types";

export default function Ingest() {
  const { name = "" } = useParams();
  const [manifest, setManifest] = useState<Manifest | null>(null);

  useEffect(() => {
    api.getIngest(name).then(setManifest);
  }, [name]);

  if (!manifest) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>
        <Link to={`/sessions/${name}`}>{name}</Link> &mdash; ingest
      </h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>src</th>
              <th>type</th>
              <th>w x h</th>
              <th>rotation</th>
              <th className="num">duration_s</th>
              <th>hdr</th>
              <th>proxy_verified</th>
            </tr>
          </thead>
          <tbody>
            {manifest.sources.map((s) => (
              <tr key={s.src}>
                <td className="src-cell">{s.src}</td>
                <td>{s.type}</td>
                <td>
                  {s.w}x{s.h}
                </td>
                <td>{s.rotation}</td>
                <td className="num">{s.type === "video" ? s.duration_s : ""}</td>
                <td>{String(s.hdr)}</td>
                <td>{String(s.proxy_verified)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {manifest.warnings && manifest.warnings.length > 0 && (
        <>
          <h3>Warnings</h3>
          <ul>
            {manifest.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}
      <h3>Target</h3>
      <pre>{JSON.stringify(manifest.target, null, 2)}</pre>
      <h3>Music</h3>
      <pre>{JSON.stringify(manifest.music, null, 2)}</pre>
    </>
  );
}
