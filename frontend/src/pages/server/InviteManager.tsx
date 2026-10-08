import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useFriends } from "../../api/hooks";
import type { InviteEntry, ServerDetail } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { ErrorText } from "../../components/ErrorText";
import { Icon } from "../../components/Icon";
import { SelectField } from "../../components/Field";
import { useUi } from "../../store/ui";
import { copyText } from "../../utils/clipboard";
import { formatDateTime } from "../../utils/format";

export function inviteUrl(code: string): string {
  return `${window.location.origin}/invite/${code}`;
}

export function InviteManager({ server, withFriends }: { server: ServerDetail; withFriends: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const friends = useFriends();
  const [maxUses, setMaxUses] = useState("");
  const [expires, setExpires] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const invites = useQuery({ queryKey: ["invites", server.id], queryFn: () => api.get<InviteEntry[]>(`/servers/${server.id}/invites`) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["invites", server.id] });
  const create = useMutation({
    mutationFn: () => api.post<InviteEntry>(`/servers/${server.id}/invites`, { max_uses: maxUses ? Number(maxUses) : null, expires_in_hours: expires ? Number(expires) : null }),
    onSuccess: refresh,
  });
  const revoke = useMutation({ mutationFn: (code: string) => api.del(`/servers/${server.id}/invites/${code}`), onSuccess: refresh });
  const sendToFriends = useMutation({
    mutationFn: (code: string) => api.post<{ sent: number }>(`/servers/${server.id}/invite-friends`, { user_ids: [...selected], invite_code: code }),
    onSuccess: (result) => {
      push("success", t("server.invites_sent", { count: result.sent }));
      setSelected(new Set());
    },
  });
  const copy = async (code: string) => {
    const ok = await copyText(inviteUrl(code));
    push(ok ? "success" : "error", ok ? t("common.copied") : t("developer.copy_failed"));
  };
  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  const list = invites.data ?? [];
  const primary = list[0]?.code ?? server.invite_code;

  return (
    <div className="invite-manager">
      <h3>{t("server.invite_links")}</h3>
      {list.length === 0 ? <p className="muted">{t("server.no_invites")}</p> : null}
      <ul className="list">
        {list.map((invite) => (
          <li key={invite.code} className="list__row">
            <div className="list__item list__item--stack">
              <code>{inviteUrl(invite.code)}</code>
              <span className="muted">
                {t("server.invite_uses", { uses: invite.uses, max: invite.max_uses ?? "∞" })}
                {invite.expires_at ? ` · ${t("server.invite_expires", { date: formatDateTime(invite.expires_at) })}` : ""}
              </span>
            </div>
            <button type="button" className="icon-button" onClick={() => void copy(invite.code)} aria-label={t("common.copy")} title={t("common.copy")}>
              <Icon name="copy" />
            </button>
            <button type="button" className="icon-button icon-button--danger" onClick={() => revoke.mutate(invite.code)} aria-label={t("server.revoke_invite")} title={t("server.revoke_invite")}>
              <Icon name="trash" />
            </button>
          </li>
        ))}
      </ul>
      <div className="inline-form">
        <SelectField
          label={t("server.invite_max_uses")}
          value={maxUses}
          onChange={(event) => setMaxUses(event.target.value)}
          options={[{ value: "", label: t("server.unlimited") }, ...["1", "5", "25", "100"].map((value) => ({ value, label: value }))]}
        />
        <SelectField
          label={t("server.invite_expiry")}
          value={expires}
          onChange={(event) => setExpires(event.target.value)}
          options={[
            { value: "", label: t("server.never") },
            { value: "1", label: t("server.hours", { count: 1 }) },
            { value: "24", label: t("server.hours", { count: 24 }) },
            { value: "168", label: t("server.days", { count: 7 }) },
            { value: "720", label: t("server.days", { count: 30 }) },
          ]}
        />
        <button type="button" className="button button--primary" onClick={() => create.mutate()} disabled={create.isPending}>
          {t("server.create_invite")}
        </button>
      </div>
      <ErrorText error={create.error ?? revoke.error ?? sendToFriends.error} />
      {withFriends && primary ? (
        <>
          <h3>{t("server.invite_friends")}</h3>
          {(friends.data ?? []).length === 0 ? <p className="muted">{t("friends.none")}</p> : null}
          <ul className="list list--scroll">
            {(friends.data ?? []).map((friend) => (
              <li key={friend.id}>
                <label className="list__item">
                  <input type="checkbox" checked={selected.has(friend.id)} onChange={() => toggle(friend.id)} />
                  <Avatar name={friend.display_name} url={friend.avatar_url} size={28} /> {friend.display_name}
                </label>
              </li>
            ))}
          </ul>
          <button type="button" className="button button--outline" disabled={selected.size === 0 || sendToFriends.isPending} onClick={() => sendToFriends.mutate(primary)}>
            {t("server.send_invites", { count: selected.size })}
          </button>
        </>
      ) : null}
    </div>
  );
}
