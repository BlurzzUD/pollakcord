import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { useAuth } from "./store/auth";
import { DmPage } from "./pages/DmPage";
import { DokPage } from "./pages/DokPage";
import { DokThreadPage } from "./pages/DokThreadPage";
import { FriendsPage } from "./pages/FriendsPage";
import { HomePage } from "./pages/HomePage";
import { InvitePage } from "./pages/InvitePage";
import { ModerationPage } from "./pages/ModerationPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { LandingPage } from "./pages/auth/LandingPage";
import { LoginPage } from "./pages/auth/LoginPage";
import { RecoverPage } from "./pages/auth/RecoverPage";
import { RegisterPage } from "./pages/auth/RegisterPage";
import { ServerPage } from "./pages/server/ServerPage";
import { SettingsPage } from "./pages/settings/SettingsPage";

export function App() {
  const load = useAuth((state) => state.load);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/recover" element={<RecoverPage />} />
      <Route path="/invite/:code" element={<InvitePage />} />
      <Route
        path="/app/settings/:section?"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route path="/app" element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="friends" element={<FriendsPage />} />
        <Route path="dm/:conversationId" element={<DmPage />} />
        <Route path="dok" element={<DokPage />} />
        <Route path="dok/:threadId" element={<DokThreadPage />} />
        <Route path="server/:serverId/:channelId?" element={<ServerPage />} />
        <Route path="moderation" element={<ModerationPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
