import { useTranslation } from "react-i18next";

import type { Member, Role, ServerDetail } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";

interface Group {
  key: string;
  label: string;
  color: string | null;
  members: Member[];
}

export function groupMembers(members: Member[], roles: Role[], ownerLabel: string, defaultLabel: string): Group[] {
  const custom = roles.filter((role) => !role.is_default).sort((a, b) => b.position - a.position);
  const groups: Group[] = [{ key: "owner", label: ownerLabel, color: null, members: [] }];
  custom.forEach((role) => groups.push({ key: role.id, label: role.name, color: role.color, members: [] }));
  groups.push({ key: "member", label: defaultLabel, color: null, members: [] });
  for (const member of members) {
    if (member.is_owner) {
      groups[0].members.push(member);
      continue;
    }
    const top = custom.find((role) => member.role_ids.includes(role.id));
    const target = top ? groups.find((group) => group.key === top.id) : groups.at(-1);
    target?.members.push(member);
  }
  return groups.filter((group) => group.members.length > 0);
}

export function MemberList({ server, members }: { server: ServerDetail; members: Member[] }) {
  const { t } = useTranslation();
  const presence = useLive((state) => state.presence);
  const openProfile = useUi((state) => state.openProfile);
  const status = (member: Member) => presence[member.user.id] ?? member.presence;
  const groups = groupMembers(members, server.roles, t("server.owner"), t("server.members"));
  return (
    <aside className="members" aria-label={t("server.member_list")}>
      {groups.map((group) => {
        const sorted = [...group.members].sort((a, b) => Number(status(b) === "online") - Number(status(a) === "online") || (a.nickname ?? a.user.display_name).localeCompare(b.nickname ?? b.user.display_name));
        return (
          <section key={group.key}>
            <h2 className="sidebar__heading" style={group.color ? { color: group.color } : undefined}>
              {group.label} — {group.members.length}
            </h2>
            <ul>
              {sorted.map((member) => (
                <li key={member.user.id}>
                  <button type="button" className={`member${status(member) === "online" ? "" : " is-offline"}`} onClick={() => openProfile(member.user.id)}>
                    <Avatar name={member.nickname ?? member.user.display_name} url={member.user.avatar_url} size={32} presence={status(member)} />
                    <span className="member__name" style={group.color ? { color: group.color } : undefined}>
                      {member.nickname ?? member.user.display_name}
                    </span>
                    {member.timeout_until ? <span className="badge">{t("server.timed_out")}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </aside>
  );
}
