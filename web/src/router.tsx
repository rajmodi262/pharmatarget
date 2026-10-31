import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell } from "./app/AppShell";

// Every page is code-split: the shell loads once, and a page's code arrives
// only when someone opens it. The landing story no longer pays for the Model
// Lab's charts, and a rep opening a call list never downloads the brief.
export const router = createBrowserRouter([
  // The story is the front door. Someone arriving cold gets the argument
  // before the instrument; the tool is one click away at every moment.
  { path: "/", lazy: () => import("./story/Story").then((m) => ({ Component: m.Story })) },
  { path: "/story", lazy: () => import("./story/Story").then((m) => ({ Component: m.Story })) },
  // Present mode: the 10-slide steering-committee brief, outside the tool shell.
  { path: "/brief", lazy: () => import("./brief/Brief").then((m) => ({ Component: m.Brief })) },
  {
    path: "/app",
    element: <AppShell />,
    children: [
      { index: true, lazy: () => import("./app/Overview").then((m) => ({ Component: m.Overview })) },
      { path: "case", lazy: () => import("./app/Case").then((m) => ({ Component: m.Case })) },
      { path: "lab", lazy: () => import("./app/Lab").then((m) => ({ Component: m.Lab })) },
      { path: "models", lazy: () => import("./app/ModelLab").then((m) => ({ Component: m.ModelLab })) },
      { path: "targets", lazy: () => import("./app/Targets").then((m) => ({ Component: m.Targets })) },
      { path: "calls", lazy: () => import("./app/CallList").then((m) => ({ Component: m.CallList })) },
      { path: "territories", lazy: () => import("./app/Territories").then((m) => ({ Component: m.Territories })) },
      { path: "response", lazy: () => import("./app/Response").then((m) => ({ Component: m.ResponseRoute })) },
      { path: "method", lazy: () => import("./app/Method").then((m) => ({ Component: m.Method })) },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
