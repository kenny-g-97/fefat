import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "./index.css"
import App from "./App.tsx"

const rootElement = document.getElementById("root")
if (rootElement === null) {
  throw new Error('Expected an element with id "root" in index.html. Got none.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>
)
