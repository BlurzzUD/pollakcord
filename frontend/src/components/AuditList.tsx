import { useTranslation } from "react-i18next";

import type { AuditEntry } from "../api/types";
import { formatDateTime } from "../utils/format";

function summarize(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && value.length === 0))
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

export function AuditList({ entries }: { entries: AuditEntry[] }) {
  const { t } = useTranslation();
  return (
    <table className="audit-table">
      <thead>
        <tr>
          <th scope="col">{t("audit.time")}</th>
          <th scope="col">{t("audit.actor")}</th>
          <th scope="col">{t("audit.action")}</th>
          <th scope="col">{t("audit.target")}</th>
          <th scope="col">{t("audit.details")}</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.id}>
            <td>
              <time dateTime={entry.created_at}>{formatDateTime(entry.created_at)}</time>
            </td>
            <td>{entry.actor?.display_name ?? "—"}</td>
            <td>{t(`audit.actions.${entry.action.replace(".", "_")}`, { defaultValue: entry.action })}</td>
            <td>{entry.target_user ? entry.target_user.display_name : (entry.target_type ?? "—")}</td>
            <td className="muted">{summarize(entry.details)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
