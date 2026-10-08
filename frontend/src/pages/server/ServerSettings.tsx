import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ServerDetail } from "../../api/types";
import { Modal } from "../../components/Modal";
import { can } from "../../utils/permissions";
import { AuditPanel } from "./panels/AuditPanel";
import { BansPanel } from "./panels/BansPanel";
import { ChannelsPanel } from "./panels/ChannelsPanel";
import { InviteManager } from "./InviteManager";
import { MembersPanel } from "./panels/MembersPanel";
import { OverviewPanel } from "./panels/OverviewPanel";
import { ReportsPanel } from "./panels/ReportsPanel";
import { RolesPanel } from "./panels/RolesPanel";

type Tab = "overview" | "roles" | "channels" | "members" | "invites" | "bans" | "reports" | "audit";

export function ServerSettings({ server, onClose }: { server: ServerDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const allowed = (permission: string) => server.is_owner || can(server.my_permissions, permission);
  const tabs: Tab[] = (
    [
      ["overview", true],
      ["roles", allowed("manage_roles")],
      ["channels", allowed("manage_channels")],
      ["members", allowed("manage_members") || allowed("kick_members") || allowed("manage_roles")],
      ["invites", allowed("create_invite")],
      ["bans", allowed("ban_members")],
      ["reports", allowed("manage_messages")],
      ["audit", allowed("view_audit_log")],
    ] as [Tab, boolean][]
  )
    .filter(([, visible]) => visible)
    .map(([tab]) => tab);
  const [tab, setTab] = useState<Tab>(tabs[0]);

  return (
    <Modal title={t("server.settings_title", { name: server.name })} onClose={onClose} wide>
      <div className="settings-modal">
        <div className="tabs tabs--vertical" role="tablist" aria-orientation="vertical">
          {tabs.map((value) => (
            <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>
              {t(`server.tab.${value}`)}
            </button>
          ))}
        </div>
        <div role="tabpanel" className="settings-modal__panel">
          {tab === "overview" ? <OverviewPanel server={server} /> : null}
          {tab === "roles" ? <RolesPanel server={server} /> : null}
          {tab === "channels" ? <ChannelsPanel server={server} /> : null}
          {tab === "members" ? <MembersPanel server={server} /> : null}
          {tab === "invites" ? <InviteManager server={server} withFriends={false} /> : null}
          {tab === "bans" ? <BansPanel server={server} /> : null}
          {tab === "reports" ? <ReportsPanel server={server} /> : null}
          {tab === "audit" ? <AuditPanel server={server} /> : null}
        </div>
      </div>
    </Modal>
  );
}
