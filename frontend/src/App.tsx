import { NavLink, Route, Routes, useMatch } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { DocumentsPage } from "./pages/DocumentsPage";

export function App() {
  // a saved conversation (/c/:id) is still the lookup page
  const inConversation = useMatch("/c/:id") !== null;
  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
          grounded<span>-rag</span>
        </NavLink>
        <nav className="topnav">
          <NavLink to="/" end className={({ isActive }) => (isActive || inConversation ? "active" : "")}>
            Tra cứu
          </NavLink>
          <NavLink to="/documents">Văn bản</NavLink>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/c/:id" element={<ChatPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="*" element={<ChatPage />} />
      </Routes>
    </div>
  );
}
