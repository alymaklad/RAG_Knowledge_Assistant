import { createBrowserRouter, Navigate } from "react-router";
import { AppShell } from "./components/AppShell";
import { CourseLayout } from "./components/CourseLayout";
import { RequireAuth } from "./components/RequireAuth";
import { AuthPage } from "./pages/AuthPage";
import { ChatPage } from "./pages/ChatPage";
import { CourseSettingsPage } from "./pages/CourseSettingsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ErrorPage } from "./pages/ErrorPage";
import { InsightsPage } from "./pages/InsightsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { StudyPage } from "./pages/StudyPage";

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
              { path: "chat/:sessionId?", element: <ChatPage /> },
              { path: "documents", element: <DocumentsPage /> },
              { path: "study", element: <StudyPage /> },
              { path: "insights", element: <InsightsPage /> },
              { path: "settings", element: <CourseSettingsPage /> },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
