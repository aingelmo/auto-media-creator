import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { countClientTrash, subscribeTrashChanged } from "../trash";

/** Header bin link with a combined server + client count. */
export default function TrashLink() {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      let server = 0;
      try {
        const payload = await api.getTrash();
        server = payload.items.length;
      } catch {
        // The count is a hint, not a contract; a failed fetch must not
        // block navigation to the bin.
      }
      if (!cancelled) setCount(server + countClientTrash());
    }
    refresh();
    const unsubscribe = subscribeTrashChanged(refresh);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return (
    <Link to="/trash" className="trash-link">
      Trash
      {count !== null && count > 0 && <span className="trash-count">{count}</span>}
    </Link>
  );
}
