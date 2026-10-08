import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { Role, ServerDetail } from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { ErrorText } from "../../../components/ErrorText";
import { TextField } from "../../../components/Field";
import { useUi } from "../../../store/ui";
import { PERMISSION_BITS } from "../../../utils/permissions";

const GROUPS: Record<string, string[]> = {
  general: ["manage_server", "manage_channels", "manage_roles", "manage_members", "view_audit_log", "create_invite"],
  text: ["view_channel", "send_messages", "read_message_history", "add_reactions", "manage_messages"],
  voice: ["connect", "speak", "mute_members", "deafen_members"],
  moderation: ["kick_members", "ban_members"],
  advanced: ["administrator"],
};

export function RolesPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ name: string; color: string; position: number; permissions: string[] } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const roles = [...server.roles].sort((a, b) => b.position - a.position);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["server", server.id] });
  const mine = (permission: string) => server.is_owner || (server.my_permissions & PERMISSION_BITS[permission]) !== 0;

  const select = (role: Role) => {
    setSelectedId(role.id);
    setDraft({ name: role.name, color: role.color ?? "#6b7280", position: role.position, permissions: role.permission_names });
  };
  const save = useMutation({
    mutationFn: () => {
      const role = server.roles.find((r) => r.id === selectedId) as Role;
      return api.patch(`/servers/${server.id}/roles/${selectedId}`, {
        name: draft?.name,
        color: draft?.color,
        permissions: draft?.permissions,
        ...(role.is_default ? {} : { position: draft?.position }),
      });
    },
    onSuccess: async () => {
      await refresh();
      push("success", t("common.saved"));
    },
  });
  const create = useMutation({
    mutationFn: () => api.post<Role>(`/servers/${server.id}/roles`, { name: t("server.new_role"), permissions: [] }),
    onSuccess: async (role) => {
      await refresh();
      select(role);
    },
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/servers/${server.id}/roles/${selectedId}`),
    onSuccess: async () => {
      setSelectedId(null);
      setDraft(null);
      setDeleting(false);
      await refresh();
    },
  });
  const selected = server.roles.find((role) => role.id === selectedId);

  const toggle = (permission: string, checked: boolean) =>
    setDraft((current) => (current ? { ...current, permissions: checked ? [...current.permissions, permission] : current.permissions.filter((p) => p !== permission) } : current));

  return (
    <div className="panel panel--split">
      <div>
        <button type="button" className="button button--outline button--block" onClick={() => create.mutate()}>
          {t("server.create_role")}
        </button>
        <ul className="list">
          {roles.map((role) => (
            <li key={role.id}>
              <button type="button" className={`list__item${role.id === selectedId ? " is-active" : ""}`} onClick={() => select(role)}>
                <span className="color-dot" style={{ background: role.color ?? "var(--text-muted)" }} aria-hidden="true" />
                {role.name}
                {role.is_default ? <span className="badge">{t("server.default_role")}</span> : null}
              </button>
            </li>
          ))}
        </ul>
        <ErrorText error={create.error} />
      </div>
      {selected && draft ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <TextField label={t("server.role_name")} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} maxLength={40} />
          <div className="inline-form">
            <TextField label={t("server.role_color")} type="color" value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} />
            {!selected.is_default ? (
              <TextField label={t("server.role_position")} hint={t("server.role_position_hint")} type="number" min={0} max={1000} value={draft.position} onChange={(event) => setDraft({ ...draft, position: Number(event.target.value) })} />
            ) : null}
          </div>
          {Object.entries(GROUPS).map(([group, names]) => (
            <fieldset key={group} className="permissions">
              <legend>{t(`server.perm_group_${group}`)}</legend>
              {names.map((permission) => (
                <label key={permission} className="check">
                  <input type="checkbox" checked={draft.permissions.includes(permission)} disabled={!mine(permission)} onChange={(event) => toggle(permission, event.target.checked)} />
                  <span>
                    {t(`permissions.${permission}`)}
                    <span className="muted"> — {t(`permissions.${permission}_hint`)}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          ))}
          <ErrorText error={save.error ?? remove.error} />
          <div className="button-row">
            <button type="submit" className="button button--primary" disabled={save.isPending}>
              {t("common.save")}
            </button>
            {selected.kind === "custom" ? (
              <button type="button" className="button button--danger-ghost" onClick={() => setDeleting(true)}>
                {t("server.delete_role")}
              </button>
            ) : null}
          </div>
        </form>
      ) : (
        <p className="muted">{t("server.select_role")}</p>
      )}
      {deleting ? (
        <ConfirmDialog title={t("server.delete_role")} message={t("server.delete_role_confirm", { name: selected?.name })} danger confirmLabel={t("server.delete_role")} onCancel={() => setDeleting(false)} onConfirm={() => remove.mutate()} busy={remove.isPending} />
      ) : null}
    </div>
  );
}
