import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { DashboardScreen } from "./components/DashboardScreen";
import "./styles/global.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Missing #root container");
}

createRoot(container).render(
  <StrictMode>
    <DashboardScreen />
  </StrictMode>,
);
