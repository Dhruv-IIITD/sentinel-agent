import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { HelpCenter } from "./pages/HelpCenter";
import { OperatorDesk } from "./pages/OperatorDesk";

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<OperatorDesk />} />
        <Route path="/help" element={<HelpCenter />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
