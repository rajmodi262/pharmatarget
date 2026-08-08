import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { ApiError } from "./lib/api";
import { router } from "./router";
import "./design/tokens.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Pipeline output is immutable between runs -- there is nothing to
      // re-fetch on window focus, and doing so would flicker a demo.
      refetchOnWindowFocus: false,
      staleTime: 5 * 60_000,
      // Retry a cold-starting host, but NEVER retry a 503. A 503 here means the
      // pipeline has not been built -- retrying cannot change that, and each
      // attempt just extends how long the user stares at a skeleton before
      // being told something actionable.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status === 503) return false;
        return failureCount < 2;
      },
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
