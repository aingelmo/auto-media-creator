import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Candidate } from "../types";

export default function Candidates() {
  const { name = "" } = useParams();
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);

  useEffect(() => {
    api.getCandidates(name).then((p) => setCandidates(p.candidates));
  }, [name]);

  if (!candidates) return <p>Loading&hellip;</p>;

  return (
    <>
      <h2>
        <Link to={`/sessions/${name}`}>{name}</Link> &mdash; candidates ({candidates.length})
      </h2>
      {candidates.map((c) => (
        <div className="candidate" key={c.id}>
          <h3>
            {c.id} &mdash; {c.kind}
          </h3>
          <p>
            src={c.src} score_cv={c.score_cv} admits_slots={JSON.stringify(c.admits_slots)}
          </p>
          {c.peak_urls.map((url) => (
            <img key={url} src={url} alt={`${c.id} peak frame`} height={160} />
          ))}
        </div>
      ))}
    </>
  );
}
