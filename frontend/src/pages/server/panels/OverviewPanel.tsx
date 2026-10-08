import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../../api/client";
import { useMembers } from "../../../api/hooks";
import type { ServerDetail } from "../../../api/types";
import { Avatar } from "../../../components/Avatar";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { CopyId } from "../../../components/CopyId";
import { ErrorText } from "../../../components/ErrorText";
import { SelectField, TextAreaField, TextField, Toggle } from "../../../components/Field";
import { useUi } from "../../../store/ui";
import { can } from "../../../utils/permissions";

export function OverviewPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const canManage = server.is_owner || can(server.my_permissions, "manage_server");
  const members = useMembers(server.id);
  const fileInput = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(server.name);
  const [description, setDescription] = useState(server.description);
  const [settings, setSettings] = useState(server.moderation_settings);
  const [newOwner, setNewOwner] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteName, setDeleteName] = useState("");
  const refresh = () => Promise.all([queryClient.invalidateQueries({ queryKey: ["server", server.id] }), queryClient.invalidateQueries({ queryKey: ["servers"] })]);

  const save = useMutation({
    mutationFn: () => api.patch(`/servers/${server.id}`, { name, description, moderation_settings: settings }),
    onSuccess: async () => {
      await refresh();
      push("success", t("common.saved"));
    },
  });
  const icon = useMutation({
    mutationFn: (file: File | null) => (file ? api.upload(`/servers/${server.id}/icon`, file) : api.del(`/servers/${server.id}/icon`)),
    onSuccess: refresh,
  });
  const transfer = useMutation({
    mutationFn: () => api.patch(`/servers/${server.id}`, { owner_id: newOwner }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/servers/${server.id}`, { confirm_name: deleteName }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      navigate("/app");
    },
  });

  return (
    <div className="panel">
      <div className="panel__row">
        <Avatar name={server.name} url={server.icon_url} size={72} rounded={false} />
        {canManage ? (
          <div className="button-row">
            <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(event) => event.target.files?.[0] && icon.mutate(event.target.files[0])} />
            <button type="button" className="button button--outline" onClick={() => fileInput.current?.click()}>
              {t("settings.upload_image")}
            </button>
            {server.icon_url ? (
              <button type="button" className="button button--ghost" onClick={() => icon.mutate(null)}>
                {t("settings.remove_image")}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <ErrorText error={icon.error} />
      <TextField label={t("server.name")} value={name} onChange={(event) => setName(event.target.value)} maxLength={60} disabled={!canManage} />
      <TextAreaField label={t("server.description")} value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} rows={3} disabled={!canManage} />
      <CopyId value={server.id} label={t("developer.server_id")} />
      <h3>{t("server.moderation_settings")}</h3>
      <Toggle label={t("server.reports_enabled")} hint={t("server.reports_enabled_hint")} checked={settings.reports_enabled} disabled={!canManage} onChange={(value) => setSettings({ ...settings, reports_enabled: value })} />
      <Toggle label={t("server.invites_enabled")} hint={t("server.invites_enabled_hint")} checked={settings.invites_enabled} disabled={!canManage} onChange={(value) => setSettings({ ...settings, invites_enabled: value })} />
      <TextField
        label={t("server.max_mentions")}
        type="number"
        min={1}
        max={50}
        value={settings.max_mentions_per_message}
        disabled={!canManage}
        onChange={(event) => setSettings({ ...settings, max_mentions_per_message: Math.min(50, Math.max(1, Number(event.target.value) || 1)) })}
      />
      <ErrorText error={save.error} />
      {canManage ? (
        <button type="button" className="button button--primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {t("common.save")}
        </button>
      ) : null}
      {server.is_owner ? (
        <section className="danger-zone">
          <h3>{t("server.danger_zone")}</h3>
          <SelectField
            label={t("server.transfer_ownership")}
            hint={t("server.transfer_hint")}
            value={newOwner}
            onChange={(event) => setNewOwner(event.target.value)}
            options={[{ value: "", label: t("server.choose_member") }, ...(members.data?.members ?? []).filter((m) => !m.is_owner).map((m) => ({ value: m.user.id, label: m.nickname ?? m.user.display_name }))]}
          />
          <button type="button" className="button button--danger-ghost" disabled={!newOwner || transfer.isPending} onClick={() => transfer.mutate()}>
            {t("server.transfer")}
          </button>
          <ErrorText error={transfer.error} />
          <button type="button" className="button button--danger" onClick={() => setConfirmDelete(true)}>
            {t("server.delete")}
          </button>
        </section>
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          title={t("server.delete")}
          message={t("server.delete_confirm", { name: server.name })}
          confirmLabel={t("server.delete")}
          danger
          busy={remove.isPending || deleteName !== server.name}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => deleteName === server.name && remove.mutate()}
        />
      ) : null}
      {confirmDelete ? (
        <div className="modal-extra">
          <TextField label={t("server.type_name_to_confirm")} value={deleteName} onChange={(event) => setDeleteName(event.target.value)} />
          <ErrorText error={remove.error} />
        </div>
      ) : null}
    </div>
  );
}
