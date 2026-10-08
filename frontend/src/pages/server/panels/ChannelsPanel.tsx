import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { Channel, ServerDetail } from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { CopyId } from "../../../components/CopyId";
import { ErrorText } from "../../../components/ErrorText";
import { Icon } from "../../../components/Icon";
import { SelectField, TextField } from "../../../components/Field";
import { useUi } from "../../../store/ui";
import { CHANNEL_PERMISSIONS } from "../../../utils/permissions";

type Mode = "inherit" | "allow" | "deny";
type Target = { scope: "channels" | "categories"; id: string; name: string };

function OverwritesEditor({ server, target }: { server: ServerDetail; target: Target }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const [roleId, setRoleId] = useState(server.roles.find((role) => role.is_default)?.id ?? "");
  const rules = useQuery({ queryKey: ["overwrites", target.scope, target.id], queryFn: () => api.get<{ target_type: string; target_id: string; allow: string[]; deny: string[] }[]>(`/${target.scope}/${target.id}/overwrites`) });
  const current = rules.data?.find((rule) => rule.target_type === "role" && rule.target_id === roleId);
  const [draft, setDraft] = useState<Record<string, Mode> | null>(null);
  const modes: Record<string, Mode> =
    draft ?? Object.fromEntries(CHANNEL_PERMISSIONS.map((name) => [name, current?.allow.includes(name) ? "allow" : current?.deny.includes(name) ? "deny" : "inherit"]));
  const refresh = async () => {
    setDraft(null);
    await queryClient.invalidateQueries({ queryKey: ["overwrites", target.scope, target.id] });
    await queryClient.invalidateQueries({ queryKey: ["server", server.id] });
  };
  const save = useMutation({
    mutationFn: () =>
      api.put(`/${target.scope}/${target.id}/overwrites/role/${roleId}`, {
        allow: CHANNEL_PERMISSIONS.filter((name) => modes[name] === "allow"),
        deny: CHANNEL_PERMISSIONS.filter((name) => modes[name] === "deny"),
      }),
    onSuccess: async () => {
      await refresh();
      push("success", t("common.saved"));
    },
  });
  const reset = useMutation({ mutationFn: () => api.del(`/${target.scope}/${target.id}/overwrites/role/${roleId}`), onSuccess: refresh });

  return (
    <div className="overwrites">
      <h4>{t("server.permissions_for", { name: target.name })}</h4>
      <SelectField
        label={t("server.role")}
        value={roleId}
        onChange={(event) => {
          setRoleId(event.target.value);
          setDraft(null);
        }}
        options={server.roles.map((role) => ({ value: role.id, label: role.name }))}
      />
      <table className="overwrite-table">
        <caption className="sr-only">{t("server.permissions_for", { name: target.name })}</caption>
        <tbody>
          {CHANNEL_PERMISSIONS.map((name) => (
            <tr key={name}>
              <th scope="row">{t(`permissions.${name}`)}</th>
              <td>
                <select aria-label={t(`permissions.${name}`)} value={modes[name]} onChange={(event) => setDraft({ ...modes, [name]: event.target.value as Mode })}>
                  <option value="inherit">{t("server.perm_inherit")}</option>
                  <option value="allow">{t("server.perm_allow")}</option>
                  <option value="deny">{t("server.perm_deny")}</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ErrorText error={save.error ?? reset.error} />
      <div className="button-row">
        <button type="button" className="button button--primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {t("common.save")}
        </button>
        <button type="button" className="button button--ghost" onClick={() => reset.mutate()} disabled={!current}>
          {t("server.perm_reset")}
        </button>
      </div>
    </div>
  );
}

export function ChannelsPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"text" | "voice">("text");
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [removing, setRemoving] = useState<Channel | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["server", server.id] });
  const createChannel = useMutation({
    mutationFn: () => api.post(`/servers/${server.id}/channels`, { name, type: kind, category_id: categoryId || null }),
    onSuccess: async () => {
      setName("");
      await refresh();
    },
  });
  const createCategory = useMutation({
    mutationFn: () => api.post(`/servers/${server.id}/categories`, { name: categoryName }),
    onSuccess: async () => {
      setCategoryName("");
      await refresh();
    },
  });
  const rename = useMutation({
    mutationFn: () => api.patch(`/channels/${renaming?.id}`, { name: renaming?.name }),
    onSuccess: async () => {
      setRenaming(null);
      await refresh();
    },
  });
  const removeChannel = useMutation({
    mutationFn: (channel: Channel) => api.del(`/channels/${channel.id}`),
    onSuccess: async () => {
      setRemoving(null);
      await refresh();
    },
  });
  const removeCategory = useMutation({ mutationFn: (id: string) => api.del(`/categories/${id}`), onSuccess: refresh });

  return (
    <div className="panel">
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          createChannel.mutate();
        }}
      >
        <TextField label={t("channel.name")} value={name} onChange={(event) => setName(event.target.value)} maxLength={60} required />
        <SelectField label={t("channel.type")} value={kind} onChange={(event) => setKind(event.target.value as "text" | "voice")} options={[{ value: "text", label: t("channel.type_text") }, { value: "voice", label: t("channel.type_voice") }]} />
        <SelectField label={t("channel.category")} value={categoryId} onChange={(event) => setCategoryId(event.target.value)} options={[{ value: "", label: t("channel.no_category") }, ...server.categories.map((c) => ({ value: c.id, label: c.name }))]} />
        <button type="submit" className="button button--primary" disabled={createChannel.isPending || !name.trim()}>
          {t("channel.create")}
        </button>
      </form>
      <ErrorText error={createChannel.error} />
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          createCategory.mutate();
        }}
      >
        <TextField label={t("channel.category_name")} value={categoryName} onChange={(event) => setCategoryName(event.target.value)} maxLength={60} />
        <button type="submit" className="button button--outline" disabled={createCategory.isPending || !categoryName.trim()}>
          {t("channel.create_category")}
        </button>
      </form>
      <ErrorText error={createCategory.error ?? removeCategory.error} />
      <div className="tree">
        {[{ id: "", name: t("channel.no_category") }, ...server.categories].map((category) => {
          const channels = server.channels.filter((channel) => (channel.category_id ?? "") === category.id);
          if (category.id === "" && channels.length === 0) {
            return null;
          }
          return (
            <section key={category.id || "none"}>
              <header className="tree__head">
                <h4>{category.name}</h4>
                {category.id ? (
                  <>
                    <button type="button" className="button button--small button--ghost" onClick={() => setTarget({ scope: "categories", id: category.id, name: category.name })}>
                      {t("server.permissions")}
                    </button>
                    <button type="button" className="icon-button icon-button--danger" onClick={() => removeCategory.mutate(category.id)} aria-label={t("channel.delete_category")} title={t("channel.delete_category")}>
                      <Icon name="trash" size={16} />
                    </button>
                  </>
                ) : null}
              </header>
              <ul className="list">
                {channels.map((channel) => (
                  <li key={channel.id} className="list__row">
                    <span className="list__item">
                      <Icon name={channel.type === "text" ? "hash" : "volume"} size={18} />
                      {renaming?.id === channel.id ? (
                        <input aria-label={t("channel.name")} value={renaming.name} onChange={(event) => setRenaming({ id: channel.id, name: event.target.value })} onKeyDown={(event) => event.key === "Enter" && rename.mutate()} autoFocus />
                      ) : (
                        channel.name
                      )}
                      <CopyId value={channel.id} label={t("developer.channel_id")} />
                    </span>
                    {renaming?.id === channel.id ? (
                      <button type="button" className="button button--small button--primary" onClick={() => rename.mutate()}>
                        {t("common.save")}
                      </button>
                    ) : (
                      <button type="button" className="icon-button" onClick={() => setRenaming({ id: channel.id, name: channel.name })} aria-label={t("channel.rename")} title={t("channel.rename")}>
                        <Icon name="edit" size={16} />
                      </button>
                    )}
                    <button type="button" className="button button--small button--ghost" onClick={() => setTarget({ scope: "channels", id: channel.id, name: channel.name })}>
                      {t("server.permissions")}
                    </button>
                    <button type="button" className="icon-button icon-button--danger" onClick={() => setRemoving(channel)} aria-label={t("channel.delete")} title={t("channel.delete")}>
                      <Icon name="trash" size={16} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      <ErrorText error={rename.error} />
      {target ? <OverwritesEditor key={`${target.scope}-${target.id}`} server={server} target={target} /> : null}
      {removing ? (
        <ConfirmDialog title={t("channel.delete")} message={t("channel.delete_confirm", { name: removing.name })} danger confirmLabel={t("channel.delete")} onCancel={() => setRemoving(null)} onConfirm={() => removeChannel.mutate(removing)} busy={removeChannel.isPending} />
      ) : null}
    </div>
  );
}
