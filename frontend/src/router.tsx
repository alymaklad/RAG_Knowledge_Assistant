import { createBrowserRouter, Navigate } from "react-router";
import { AppShell } from "./components/AppShell";
import { CourseLayout } from "./components/CourseLayout";
import { RequireAuth } from "./components/RequireAuth";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ErrorPage } from "./pages/ErrorPage";
import { NotFoundPage } from "./pages/NotFoundPage";

// Course sections load on demand: the chat and study pages carry the Markdown + KaTeX bundle.
export const router = createBrowserRouter([
  { path: "/login", element: <AuthPage mode="login" /> },
  { path: "/register", element: <AuthPage mode="register" /> },
  {
    element: <RequireAuth />,
    errorElement: <ErrorPage />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          {
            path: "courses/:courseId",
            element: <CourseLayout />,
            children: [
              { index: true, element: <Navigate to="chat" replace /> },
              {
                path: "chat/:sessionId?",
                lazy: () => import("./pages/ChatPage").then((m) => ({ Component: m.ChatPage })),
              },
              {
                path: "documents",
                lazy: () =>
                  import("./pages/DocumentsPage").then((m) => ({ Component: m.DocumentsPage })),
              },
              {
                path: "study",
                lazy: () => import("./pages/StudyPage").then((m) => ({ Component: m.StudyPage })),
              },
              {
                path: "insights",
                lazy: () =>
                  import("./pages/InsightsPage").then((m) => ({ Component: m.InsightsPage })),
              },
              {
                path: "settings",
                lazy: () =>
                  import("./pages/CourseSettingsPage").then((m) => ({
                    Component: m.CourseSettingsPage,
                  })),
              },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
