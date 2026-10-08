import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ServerSummary } from "../api/types";
import { Avatar } from "../components/Avatar";
import { ErrorText } from "../components/ErrorText";
import { useAuth } from "../store/auth";
import { AuthLayout } from "./auth/AuthLayout";

export function InvitePage() {
  const { t } = useTranslation();
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const status = useAuth((state) => state.status);
  const preview = useQuery({ queryKey: ["invite", code], queryFn: () => api.get<{ server: ServerSummary }>(`/invites/${code}`), retry: false });
  const accept = useMutation({
    mutationFn: () => api.post<{ server_id: string }>(`/invites/${code}/accept`),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      navigate(`/app/server/${result.server_id}`, { replace: true });
    },
  });
  const next = encodeURIComponent(`/invite/${code}`);

  return (
    <AuthLayout title={t("invite.title")} subtitle={preview.data ? t("invite.you_are_invited") : undefined}>
      {preview.isLoading ? <p role="status">{t("common.loading")}</p> : null}
      {preview.isError ? (
        <p className="form-error" role="alert">
          {t("errors.invite_invalid")}
        </p>
      ) : null}
      {preview.data ? (
        <div className="invite-card">
          <Avatar name={preview.data.server.name} url={preview.data.server.icon_url} size={72} rounded={false} />
          <h2>{preview.data.server.name}</h2>
          {preview.data.server.description ? <p className="muted">{preview.data.server.description}</p> : null}
          <p className="muted">{t("invite.members", { count: preview.data.server.member_count ?? 0 })}</p>
          {status === "authenticated" ? (
            <>
              <ErrorText error={accept.error} />
              <button type="button" className="button button--primary button--block" onClick={() => accept.mutate()} disabled={accept.isPending}>
                {t("invite.join")}
              </button>
            </>
          ) : (
            <>
              <p>{t("invite.login_required")}</p>
              <div className="button-row">
                <Link className="button button--primary" to={`/login?next=${next}`}>
                  {t("auth.login")}
                </Link>
                <Link className="button button--outline" to={`/register?next=${next}`}>
                  {t("auth.register")}
                </Link>
              </div>
            </>
          )}
        </div>
      ) : null}
    </AuthLayout>
  );
}
