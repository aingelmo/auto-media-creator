import { useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import Candidates from "./pages/Candidates";
import Hooks from "./pages/Hooks";
import Ingest from "./pages/Ingest";
import Index from "./pages/Index";
import New from "./pages/New";
import Planner from "./pages/Planner";
import Selection from "./pages/Selection";
import Session from "./pages/Session";

function ThemeToggle() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "dark");

  const toggle = () => {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    setTheme(next);
  };

  return (
    <button type="button" onClick={toggle}>
      {theme === "light" ? "dark mode" : "light mode"}
    </button>
  );
}

export default function App() {
  const navigate = useNavigate();

  return (
    <div className="app-shell" style={{ flexDirection: "column", width: "100%" }}>
      <header className="app-header">
        <Link to="/">
          <h1>edl-agent</h1>
        </Link>
        <div className="app-header-actions">
          <button type="button" onClick={() => navigate("/new")}>
            New session
          </button>
          <ThemeToggle />
        </div>
      </header>
      <main className="app-body">
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/new" element={<New />} />
          <Route path="/sessions/:name" element={<Session />} />
          <Route path="/sessions/:name/ingest" element={<Ingest />} />
          <Route path="/sessions/:name/candidates" element={<Candidates />} />
          <Route path="/sessions/:name/hooks" element={<Hooks />} />
          <Route path="/sessions/:name/selection" element={<Selection />} />
          <Route path="/sessions/:name/planner" element={<Planner />} />
        </Routes>
      </main>
    </div>
  );
}
