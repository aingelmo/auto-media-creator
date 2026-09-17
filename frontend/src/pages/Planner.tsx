import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Edl } from "../types";

export default function Planner() {
  const { name = "" } = useParams();
  const [edl, setEdl] = useState<Edl | null>(null);

  useEffect(() => {
    api.getPlanner(name).then(setEdl);
  }, [name]);

  if (!edl) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>
        <Link to={`/sessions/${name}`}>{name}</Link> &mdash; planner (EDL)
      </h2>
      <h3>Target</h3>
      <pre>{JSON.stringify(edl.target, null, 2)}</pre>
      <h3>Clips ({edl.clips.length})</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>slot</th>
              <th>role</th>
              <th>src</th>
              <th className="num">in_s</th>
              <th className="num">out_s</th>
              <th className="num">timeline_start_f</th>
              <th className="num">timeline_end_f</th>
              <th>layout</th>
              <th>warnings</th>
            </tr>
          </thead>
          <tbody>
            {edl.clips.map((c, i) => (
              <tr key={i}>
                <td>{c.slot}</td>
                <td>{c.role}</td>
                <td>{c.src}</td>
                <td className="num">{c.in_s.toFixed(2)}</td>
                <td className="num">{c.out_s.toFixed(2)}</td>
                <td className="num">{c.timeline_start_f}</td>
                <td className="num">{c.timeline_end_f}</td>
                <td>{c.layout}</td>
                <td>{c.warnings.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Audio</h3>
      <pre>{JSON.stringify(edl.audio, null, 2)}</pre>
    </>
  );
}
