import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { BotApplication } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { BotBadge } from "../../components/BotBadge";
import { CopyId } from "../../components/CopyId";
import { ErrorText } from "../../components/ErrorText";
import { TextField } from "../../components/Field";
import { Modal } from "../../components/Modal";
import { useAuth } from "../../store/auth";

type Action = { kind: "create" | "edit" | "reveal" | "regenerate" | "delete"; bot?: BotApplication };

export function BotsSection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["my-bots"], queryFn: () => api.get<BotApplication[]>("/me/bots"), enabled: Boolean(me && !me.is_bot) });
  const [action, setAction] = useState<Action | null>(null);
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["my-bots"] });
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      if (!action) return;
      const path = `/me/bots/${action.bot?.bot_id}`;
      if (action.kind === "create") return api.post<BotApplication & { token: string }>("/me/bots", { username, display_name: displayName, password });
      if (action.kind === "edit") return api.patch<BotApplication>(path, { username, display_name: displayName });
      if (action.kind === "delete") return api.del(path, { password, confirm_username: confirmation });
      return api.post<{ token: string }>(`${path}/token/${action.kind}`, { password });
    },
    onSuccess: async (result) => {
      if (result && typeof result === "object" && "token" in result) setToken(String(result.token));
      setPassword("");
      setAction(null);
      mutation.reset();
      await refresh();
    },
  });
  const image = useMutation({
    mutationFn: ({ botId, kind, file }: { botId: string; kind: string; file: File | null }) => file ? api.upload(`/me/bots/${botId}/images/${kind}`, file) : api.del(`/me/bots/${botId}/images/${kind}`),
    onSuccess: refresh,
  });
  if (!me || me.is_bot) return null;
  const open = (next: Action) => {
    mutation.reset();
    image.reset();
    setPassword("");
    setConfirmation("");
    setUsername(next.bot?.user.username ?? "");
    setDisplayName(next.bot?.user.display_name ?? "");
    setAction(next);
  };
  const close = () => { setAction(null); setPassword(""); };
  return (
    <section className="section bot-settings">
      <h3>{t("bots.title")}</h3>
      <p className="muted">{t("bots.intro")}</p>
      <p className="notice">{t("bots.limit")}</p>
      <button type="button" className="button button--primary" disabled={query.isPending || (query.data?.length ?? 0) >= 3} onClick={() => open({ kind: "create" })}>{t("bots.create")}</button>
      <ErrorText error={query.error} />
      <ul className="list">
        {(query.data ?? []).map((bot) => <li key={bot.bot_id} className="bot-card">
          <div className="button-row"><Avatar name={bot.user.display_name} url={bot.user.avatar_url} size={40} /><strong>{bot.user.display_name}</strong><BotBadge isBot /><span className="muted">@{bot.user.username}</span></div>
          <CopyId value={bot.install_code} label={t("bots.install_code")} always />
          <div className="button-row">
            {(["edit", "reveal", "regenerate", "delete"] as const).map((kind) => <button key={kind} type="button" className={`button button--small ${kind === "delete" ? "button--danger-ghost" : "button--outline"}`} onClick={() => open({ kind, bot })}>{t(`bots.${kind}`)}</button>)}
          </div>
        </li>)}
      </ul>
      {query.data?.length === 0 ? <p className="muted">{t("bots.empty")}</p> : null}
      {action ? <Modal title={t(`bots.${action.kind}`)} onClose={mutation.isPending || image.isPending ? () => undefined : close}>
        <form onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          {action.kind === "create" || action.kind === "edit" ? <>
            <TextField label={t("bots.username")} value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={24} autoComplete="off" />
            <TextField label={t("bots.display_name")} value={displayName} onChange={(event) => setDisplayName(event.target.value)} required maxLength={32} />
          </> : null}
          {action.kind === "edit" && action.bot ? <div>
            {(["avatar", "banner"] as const).map((kind) => <div key={kind} className="field">
              <TextField label={t(`bots.${kind}`)} type="file" accept="image/png,image/jpeg,image/webp,image/gif" disabled={image.isPending} onChange={(event) => { const file = event.target.files?.[0]; if (file) image.mutate({ botId: action.bot!.bot_id, kind, file }); event.target.value = ""; }} />
              <button type="button" className="button button--small button--ghost" disabled={image.isPending} onClick={() => image.mutate({ botId: action.bot!.bot_id, kind, file: null })}>{t("bots.remove_image", { kind: t(`bots.${kind}`) })}</button>
            </div>)}
            <ErrorText error={image.error} />
          </div> : null}
          {action.kind === "reveal" || action.kind === "regenerate" ? <p className="notice">{t("bots.token_rotation")}</p> : null}
          {action.kind === "delete" ? <TextField label={t("bots.confirm_delete", { username: action.bot?.user.username })} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" required /> : null}
          {action.kind !== "edit" ? <TextField label={t("bots.password")} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={128} /> : null}
          <ErrorText error={mutation.error} />
          <div className="button-row"><button type="button" className="button button--ghost" disabled={mutation.isPending} onClick={close}>{t("common.cancel")}</button><button type="submit" className="button button--primary" disabled={mutation.isPending || image.isPending || (action.kind === "delete" && confirmation !== action.bot?.user.username)}>{t(`bots.${action.kind}`)}</button></div>
        </form>
      </Modal> : null}
      {token ? <Modal title={t("bots.token_title")} onClose={() => setToken(null)}><p className="notice">{t("bots.token_once")}</p><TextField label={t("bots.token")} value={token} readOnly autoComplete="off" spellCheck={false} /><button type="button" className="button button--primary" onClick={() => setToken(null)}>{t("bots.token_saved")}</button></Modal> : null}
    </section>
  );
}
