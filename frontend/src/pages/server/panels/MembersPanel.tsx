import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import { useMembers } from "../../../api/hooks";
import type { Member, ServerDetail } from "../../../api/types";
import { Avatar } from "../../../components/Avatar";
import { CopyId } from "../../../components/CopyId";
import { ErrorText } from "../../../components/ErrorText";
import { Modal } from "../../../components/Modal";
import { SelectField, TextField } from "../../../components/Field";
import { useAuth } from "../../../store/auth";
import { can } from "../../../utils/permissions";

const TIMEOUTS = ["0", "5", "60", "1440", "10080"];

export function MembersPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const meId = useAuth((state) => state.me?.id);
  const members = useMembers(server.id);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<Member | null>(null);
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [banReason, setBanReason] = useState("");
  const topPosition = (ids: string[]) => Math.max(0, ...server.roles.filter((role) => ids.includes(role.id)).map((role) => role.position));
  const myTop = server.is_owner ? Infinity : topPosition(server.my_role_ids);
  const outranks = (member: Member) => !member.is_owner && myTop > (server.is_owner ? -1 : topPosition(member.role_ids)) && member.user.id !== meId;
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["members", server.id] }), queryClient.invalidateQueries({ queryKey: ["server", server.id] })]);
  const run = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: async () => {
      setEditing(null);
      await refresh();
    },
  });
  const list = (members.data?.members ?? []).filter((member) => `${member.nickname ?? ""} ${member.user.display_name} ${member.user.username}`.toLowerCase().includes(filter.toLowerCase()));
  const open = (member: Member) => {
    setEditing(member);
    setRoleIds(member.role_ids);
    setBanReason("");
  };

  return (
    <div className="panel">
      <TextField label={t("server.filter_members")} value={filter} onChange={(event) => setFilter(event.target.value)} type="search" />
      <ErrorText error={run.error} />
      <ul className="people">
        {list.map((member) => (
          <li key={member.user.id}>
            <span className="people__main">
              <Avatar name={member.user.display_name} url={member.user.avatar_url} size={36} />
              <span>
                <strong>{member.nickname ?? member.user.display_name}</strong>
                <span className="muted">
                  @{member.user.username}
                  {member.is_owner ? ` · ${t("server.owner")}` : ""}
                </span>
              </span>
            </span>
            {outranks(member) ? (
              <button type="button" className="button button--small" onClick={() => open(member)}>
                {t("server.manage")}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {editing ? (
        <Modal title={t("server.manage_member", { name: editing.nickname ?? editing.user.display_name })} onClose={() => setEditing(null)}>
          <CopyId value={editing.user.id} label={t("developer.user_id")} />
          {can(server.my_permissions, "manage_roles") || server.is_owner ? (
            <fieldset className="permissions">
              <legend>{t("server.roles")}</legend>
              {server.roles
                .filter((role) => !role.is_default && (server.is_owner || role.position < myTop))
                .map((role) => (
                  <label key={role.id} className="check">
                    <input type="checkbox" checked={roleIds.includes(role.id)} onChange={(event) => setRoleIds(event.target.checked ? [...roleIds, role.id] : roleIds.filter((id) => id !== role.id))} />
                    <span style={role.color ? { color: role.color } : undefined}>{role.name}</span>
                  </label>
                ))}
              <button type="button" className="button button--small button--primary" onClick={() => run.mutate(() => api.patch(`/servers/${server.id}/members/${editing.user.id}`, { role_ids: roleIds }))}>
                {t("server.save_roles")}
              </button>
            </fieldset>
          ) : null}
          {can(server.my_permissions, "manage_members") || server.is_owner ? (
            <SelectField
              label={t("server.timeout")}
              hint={t("server.timeout_hint")}
              value=""
              onChange={(event) => run.mutate(() => api.patch(`/servers/${server.id}/members/${editing.user.id}`, { timeout_minutes: Number(event.target.value) }))}
              options={[{ value: "", label: t("server.choose_duration") }, ...TIMEOUTS.map((value) => ({ value, label: value === "0" ? t("server.timeout_clear") : t("server.timeout_minutes", { count: Number(value) }) }))]}
            />
          ) : null}
          <div className="button-row">
            {can(server.my_permissions, "kick_members") || server.is_owner ? (
              <button type="button" className="button button--danger-ghost" onClick={() => run.mutate(() => api.del(`/servers/${server.id}/members/${editing.user.id}`))}>
                {t("server.kick")}
              </button>
            ) : null}
          </div>
          {can(server.my_permissions, "ban_members") || server.is_owner ? (
            <>
              <TextField label={t("server.ban_reason")} value={banReason} onChange={(event) => setBanReason(event.target.value)} maxLength={300} />
              <button type="button" className="button button--danger" onClick={() => run.mutate(() => api.put(`/servers/${server.id}/bans/${editing.user.id}`, { reason: banReason }))}>
                {t("server.ban")}
              </button>
            </>
          ) : null}
        </Modal>
      ) : null}
    </div>
  );
}
