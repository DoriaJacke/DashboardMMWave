import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Fuentes locales (funcionan sin internet): Barlow 400/500/700 y Barlow Condensed 400/600.
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/700.css";
import "@fontsource/barlow-condensed/400.css";
import "@fontsource/barlow-condensed/600.css";

// Mismo orden que el prototipo: sistema de diseño, Bootstrap y el tema encima.
import "./styles/ds.css";
import "bootstrap/dist/css/bootstrap.min.css";
import "./styles/app.css";

import App from "./App";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
