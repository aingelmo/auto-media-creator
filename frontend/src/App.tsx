import { Link, Route, Routes } from "react-router-dom";
import Candidates from "./pages/Candidates";
import Ingest from "./pages/Ingest";
import Index from "./pages/Index";
import New from "./pages/New";
import Planner from "./pages/Planner";
import Selection from "./pages/Selection";
import Session from "./pages/Session";

export default function App() {
  return (
    <div className="app-shell" style={{ flexDirection: "column", width: "100%" }}>
      <header className="app-header">
        <Link to="/">
          <h1>edl-agent</h1>
        </Link>
      </header>
      <main className="app-body">
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/new" element={<New />} />
          <Route path="/sessions/:name" element={<Session />} />
          <Route path="/sessions/:name/ingest" element={<Ingest />} />
          <Route path="/sessions/:name/candidates" element={<Candidates />} />
          <Route path="/sessions/:name/selection" element={<Selection />} />
          <Route path="/sessions/:name/planner" element={<Planner />} />
        </Routes>
      </main>
    </div>
  );
}
