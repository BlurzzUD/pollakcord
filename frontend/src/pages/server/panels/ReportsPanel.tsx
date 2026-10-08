import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { ReportEntry, ServerDetail } from "../../../api/types";
import { EmptyState } from "../../../components/EmptyState";
import { ErrorText } from "../../../components/ErrorText";
import { TextField } from "../../../components/Field";
import { formatDateTime } from "../../../utils/format";

export function ReportsPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"open" | "resolved" | "dismissed">("open");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const reports = useQuery({ queryKey: ["server-reports", server.id, status], queryFn: () => api.get<ReportEntry[]>(`/servers/${server.id}/reports`, { status }) });
  const resolve = useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: "resolved" | "dismissed" }) => api.post(`/servers/${server.id}/reports/${id}/resolve`, { resolution, note: notes[id] ?? "" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["server-reports", server.id] }),
  });
  return (
    <div className="panel">
      <div className="tabs" role="tablist">
        {(["open", "resolved", "dismissed"] as const).map((value) => (
          <button key={value} type="button" role="tab" aria-selected={status === value} className={status === value ? "is-active" : ""} onClick={() => setStatus(value)}>
            {t(`moderation.status_${value}`)}
          </button>
        ))}
      </div>
      <ErrorText error={resolve.error} />
      {(reports.data ?? []).length === 0 ? <EmptyState icon="flag" title={t("moderation.no_reports")} /> : null}
      {(reports.data ?? []).map((report) => (
        <article key={report.id} className="report">
          <header>
            <strong>{t(`report.reasons.${report.reason}`)}</strong> <span className="muted">{formatDateTime(report.created_at)}</span>
            {report.escalated ? <span className="badge">{t("moderation.escalated")}</span> : null}
          </header>
          <p className="muted">
            {t("moderation.reported_user")}: {report.target?.display_name} · {t("moderation.reporter")}: {report.reporter?.display_name}
          </p>
          {report.details ? <p>{report.details}</p> : null}
          <ol className="report__context">
            {(report.context ?? []).map((item) => (
              <li key={item.id} className={item.reported ? "is-reported" : ""}>
                {item.deleted ? <em>{t("message.deleted")}</em> : item.content}
              </li>
            ))}
          </ol>
          {status === "open" ? (
            <>
              <TextField label={t("moderation.note")} value={notes[report.id] ?? ""} onChange={(event) => setNotes({ ...notes, [report.id]: event.target.value })} maxLength={500} />
              <div className="button-row">
                <button type="button" className="button button--primary" onClick={() => resolve.mutate({ id: report.id, resolution: "resolved" })}>
                  {t("moderation.resolve")}
                </button>
                <button type="button" className="button button--ghost" onClick={() => resolve.mutate({ id: report.id, resolution: "dismissed" })}>
                  {t("moderation.dismiss")}
                </button>
              </div>
            </>
          ) : null}
        </article>
      ))}
    </div>
  );
}
