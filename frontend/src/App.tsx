import { NavLink, Route, Routes } from "react-router-dom";
import { useTheme } from "./hooks/useTheme";
import { AgentPage } from "./pages/AgentPage";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ToolsPage } from "./pages/ToolsPage";

export default function App() {
  const [theme, toggle] = useTheme();
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Main">
        <h1>🤖 Doc Agent</h1>
        <NavLink to="/" end>
          Agent
        </NavLink>
        <NavLink to="/history">History</NavLink>
        <NavLink to="/tools">Tools</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <span className="spacer" />
        <button type="button" onClick={toggle} aria-label="Toggle theme">
          {theme === "dark" ? "☀ Light" : "🌙 Dark"}
        </button>
      </nav>
      <main className="main wide">
        <Routes>
          <Route path="/" element={<AgentPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
