import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/hooks/use-auth";
import { ProtectedRoute } from "@/components/protected-route";
import { ChatLayout } from "@/components/layout/chat-layout";
import { LoginPage } from "@/pages/login";
import { RegisterPage } from "@/pages/register";
import { ForgotPasswordPage } from "@/pages/forgot-password";
import { ChatPage } from "@/pages/chat";
import { SettingsPage } from "@/pages/settings";
import { ProfilePage } from "@/pages/profile";
import { LoadingScreen } from "@/components/loading-screen";
import { TooltipProvider } from "@/components/ui/tooltip";

export default function App() {
  const { isLoading } = useAuth();

  return (
    <TooltipProvider delayDuration={300}>
      <div className="aurora-backdrop">
        <div className="aurora-blob-3" />
      </div>
      {isLoading ? (
        <LoadingScreen />
      ) : (
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route
            element={
              <ProtectedRoute>
                <ChatLayout />
              </ProtectedRoute>
            }
          >
            {/* A single route with an optional param, not two separate Route
                entries for "/" and "/chat/:threadId" - two entries match to
                a *different* route object when threadId first appears, and
                React Router remounts ChatPage on that switch, which was
                silently dropping the in-flight reply to a brand-new chat's
                first message (its optimistic state landed on the discarded
                instance). One route with an optional param keeps the same
                matched route - and the same ChatPage instance - throughout. */}
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat/:threadId?" element={<ChatPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </TooltipProvider>
  );
}
