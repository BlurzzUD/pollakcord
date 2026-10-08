import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { ServerDetail, UserCard } from "../../../api/types";
import { Avatar } from "../../../components/Avatar";
import { EmptyState } from "../../../components/EmptyState";
import { ErrorText } from "../../../components/ErrorText";
import { formatDateTime } from "../../../utils/format";

export function BansPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const bans = useQuery({ queryKey: ["bans", server.id], queryFn: () => api.get<{ user: UserCard; reason: string; created_at: string }[]>(`/servers/${server.id}/bans`) });
  const unban = useMutation({
    mutationFn: (userId: string) => api.del(`/servers/${server.id}/bans/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bans", server.id] }),
  });
  if ((bans.data ?? []).length === 0) {
    return <EmptyState icon="block" title={t("server.no_bans")} />;
  }
  return (
    <div className="panel">
      <ErrorText error={unban.error} />
      <ul className="people">
        {(bans.data ?? []).map((ban) => (
          <li key={ban.user.id}>
            <span className="people__main">
              <Avatar name={ban.user.display_name} url={ban.user.avatar_url} size={36} />
              <span>
                <strong>{ban.user.display_name}</strong>
                <span className="muted">
                  {ban.reason || t("server.no_reason")} · {formatDateTime(ban.created_at)}
                </span>
              </span>
            </span>
            <button type="button" className="button button--small" onClick={() => unban.mutate(ban.user.id)}>
              {t("server.unban")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
