import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import type { AuditEntry, ServerDetail } from "../../../api/types";
import { AuditList } from "../../../components/AuditList";
import { EmptyState } from "../../../components/EmptyState";

export function AuditPanel({ server }: { server: ServerDetail }) {
  const { t } = useTranslation();
  const log = useInfiniteQuery({
    queryKey: ["audit", server.id],
    queryFn: ({ pageParam }) => api.get<{ entries: AuditEntry[]; has_more: boolean }>(`/servers/${server.id}/audit-logs`, { before: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.has_more ? last.entries.at(-1)?.id : undefined),
  });
  const entries = log.data?.pages.flatMap((page) => page.entries) ?? [];
  if (entries.length === 0) {
    return <EmptyState icon="shield" title={t("audit.empty")} />;
  }
  return (
    <div className="panel">
      <p className="muted">{t("audit.note")}</p>
      <div className="table-scroll">
        <AuditList entries={entries} />
      </div>
      {log.hasNextPage ? (
        <button type="button" className="button button--outline" onClick={() => void log.fetchNextPage()} disabled={log.isFetchingNextPage}>
          {t("common.load_more")}
        </button>
      ) : null}
    </div>
  );
}
