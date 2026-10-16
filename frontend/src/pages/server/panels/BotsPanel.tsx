import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { BotIntegrations, BotInstall, ServerDetail } from "../../../api/types";
import { BotBadge } from "../../../components/BotBadge";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { ErrorText } from "../../../components/ErrorText";
import { TextField } from "../../../components/Field";
import { can } from "../../../utils/permissions";

export function BotsPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const allowed = server.is_owner || can(server.my_permissions, "administrator");
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["server-bots", server.id], queryFn: () => api.get<BotIntegrations>(`/servers/${server.id}/bots`), enabled: allowed });
  const [botId, setBotId] = useState("");
  const [permissions, setPermissions] = useState(["view_channel", "read_message_history", "send_messages"]);
  const [removing, setRemoving] = useState<BotInstall | null>(null);
  const refresh = async () => {
    await Promise.all([queryClient.invalidateQueries({ queryKey: ["server-bots", server.id] }), queryClient.invalidateQueries({ queryKey: ["server", server.id] }), queryClient.invalidateQueries({ queryKey: ["members", server.id] })]);
  };
  const install = useMutation({ mutationFn: () => api.post(`/servers/${server.id}/bots`, { bot_id: botId.trim(), permissions }), onSuccess: async () => { setBotId(""); await refresh(); } });
  const remove = useMutation({ mutationFn: () => api.del(`/servers/${server.id}/bots/${removing?.bot_id}`), onSuccess: async () => { setRemoving(null); await refresh(); } });
  if (!allowed) return null;
  return <section className="section">
    <h3>{t("bots.integrations")}</h3><p className="muted">{t("bots.install_intro")}</p>
    <ErrorText error={query.error} />
    <form onSubmit={(event) => { event.preventDefault(); install.mutate(); }}>
      <TextField label={t("bots.install_code")} value={botId} onChange={(event) => setBotId(event.target.value)} inputMode="numeric" pattern="[0-9]{1,19}" required />
      <fieldset className="permissions"><legend>{t("bots.permissions")}</legend>
        {(query.data?.available_permissions ?? []).map((permission) => <label className="check" key={permission}><input type="checkbox" checked={permissions.includes(permission)} onChange={(event) => setPermissions((current) => event.target.checked ? [...current, permission] : current.filter((value) => value !== permission))} /><span>{t(`permissions.${permission}`)}</span></label>)}
      </fieldset>
      <p className="notice">{t("bots.permission_cap")}</p>
      <button type="submit" className="button button--primary" disabled={install.isPending || !query.data}>{t("bots.install")}</button><ErrorText error={install.error} />
    </form>
    <ul className="list">{(query.data?.bots ?? []).map((bot) => <li className="bot-card" key={bot.bot_id}><strong>{bot.user.display_name}</strong> <BotBadge isBot /><p className="muted">{bot.online ? t("bots.online") : t("bots.offline")}</p><p>{bot.permissions.map((permission) => t(`permissions.${permission}`)).join(", ")}</p><button type="button" className="button button--danger-ghost" onClick={() => { remove.reset(); setRemoving(bot); }}>{t("bots.remove")}</button></li>)}</ul>
    {removing ? <ConfirmDialog title={t("bots.remove")} message={t("bots.remove_confirm", { name: removing.user.display_name })} confirmLabel={t("bots.remove")} danger onCancel={() => setRemoving(null)} onConfirm={() => remove.mutate()} busy={remove.isPending} /> : null}<ErrorText error={remove.error} />
  </section>;
}
