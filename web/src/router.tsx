import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./app/AppShell";
import { Overview } from "./app/Overview";
import { Targets } from "./app/Targets";
import { Territories } from "./app/Territories";
import { ResponseRoute } from "./app/Response";
import { Method } from "./app/Method";
import { Story } from "./story/Story";

export const router = createBrowserRouter([
  // The story is the front door. Someone arriving cold gets the argument
  // before the instrument; the tool is one click away at every moment.
  { path: "/", element: <Story /> },
  { path: "/story", element: <Story /> },
  {
    path: "/app",
    element: <AppShell />,
    children: [
      { index: true, element: <Overview /> },
      { path: "targets", element: <Targets /> },
      { path: "territories", element: <Territories /> },
      { path: "response", element: <ResponseRoute /> },
      { path: "method", element: <Method /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
