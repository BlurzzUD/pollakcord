import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useLocation, useMatch } from "react-router-dom";

import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { Spinner } from "../EmptyState";
import { Toasts } from "../Toasts";
import { CallOverlay } from "./CallOverlay";
import { HomeSidebar } from "./HomeSidebar";
import { ProfileModal } from "./ProfileModal";
import { RealtimeProvider } from "./RealtimeProvider";
import { ServerRail } from "./ServerRail";
import { ServerSidebar } from "./ServerSidebar";
import { UserPanel } from "./UserPanel";
import { VoiceDock } from "./VoiceDock";

function ShellLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const serverMatch = useMatch("/app/server/:serverId/*");
  const drawerOpen = useUi((state) => state.drawerOpen);
  const setDrawer = useUi((state) => state.setDrawer);

  useEffect(() => {
    setDrawer(false);
  }, [location.pathname, setDrawer]);

  return (
    <div className="shell" data-drawer={drawerOpen}>
      <a className="skip-link" href="#main">
        {t("a11y.skip_to_content")}
      </a>
      <div className="user-css-scope shell__scope">
        <nav className="rail" aria-label={t("a11y.servers")}>
          <ServerRail />
        </nav>
        <aside className="sidebar" aria-label={t("a11y.sidebar")}>
          {serverMatch?.params.serverId ? <ServerSidebar serverId={serverMatch.params.serverId} /> : <HomeSidebar />}
          <VoiceDock />
          <UserPanel />
        </aside>
        <main id="main" className="main" tabIndex={-1}>
          <Outlet />
        </main>
        {drawerOpen ? <div className="shell__backdrop" onClick={() => setDrawer(false)} aria-hidden="true" /> : null}
      </div>
      <ProfileModal />
      <CallOverlay />
      <Toasts />
    </div>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const status = useAuth((state) => state.status);
  const location = useLocation();
  if (status === "loading") {
    return <Spinner label={t("common.loading")} />;
  }
  if (status !== "authenticated") {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return (
    <RealtimeProvider>
      <ShellLayout />
    </RealtimeProvider>
  );
}
