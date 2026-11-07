import "@/app/zod-jitless"
import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { queryClient } from "@/api/client"
import { router } from "@/app/router"
import "./index.css"

const rootElement = document.getElementById("root")
if (rootElement === null) {
  throw new Error('Expected an element with id "root" in index.html, got none.')
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
)
