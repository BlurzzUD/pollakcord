import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useClassSpaceMessages } from "../../api/hooks";
import type { ClassSpaceMessage } from "../../api/types";
import { formatDay, sameDay } from "../../utils/format";
import { ReportDialog } from "../chat/ReportDialog";
import { ConfirmDialog } from "../ConfirmDialog";
import { EmptyState, Spinner } from "../EmptyState";
import { ErrorText, errorMessage } from "../ErrorText";
import { ClassSpaceMessageItem } from "./ClassSpaceMessageItem";

const READ_DELAY_MS = 500;

export function ClassSpaceMessageList({ classId, unread }: { classId: string; unread: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const history = useClassSpaceMessages(classId);
  const scroller = useRef<HTMLDivElement>(null);
  const anchor = useRef<number | null>(null);
  const [reporting, setReporting] = useState<ClassSpaceMessage | null>(null);
  const [deleting, setDeleting] = useState<ClassSpaceMessage | null>(null);
  const messages = useMemo(() => [...(history.data?.pages ?? [])].reverse().flatMap((page) => page.messages), [history.data]);
  const newestId = messages.at(-1)?.id ?? null;
  const oldestId = messages[0]?.id ?? null;

  const remove = useMutation({
    mutationFn: (message: ClassSpaceMessage) => api.del(`/class-spaces/${classId}/messages/${message.id}`),
    onSuccess: () => {
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: ["class-space"] });
    },
    onError: () => setDeleting(null),
  });

  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element) {
      return;
    }
    if (anchor.current !== null) {
      element.scrollTop += element.scrollHeight - anchor.current;
      anchor.current = null;
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [newestId, oldestId]);

  useEffect(() => {
    if (unread === 0 || newestId === null) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      if (document.visibilityState === "hidden") {
        return;
      }
      void api.post(`/class-spaces/${classId}/read`, { message_id: newestId }).then(() => queryClient.invalidateQueries({ queryKey: ["class-space", "state"] }));
    }, READ_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [unread, newestId, classId, queryClient]);

  const loadOlder = () => {
    anchor.current = scroller.current?.scrollHeight ?? null;
    void history.fetchNextPage();
  };

  return (
    <div className="timeline">
      <div className="timeline__scroll" ref={scroller} role="log" aria-live="polite" aria-relevant="additions" aria-label={t("a11y.messages_region")}>
        {history.isPending ? <Spinner label={t("common.loading")} /> : null}
        {history.isError ? (
          <p className="form-error" role="alert">
            {errorMessage(t, history.error)}
          </p>
        ) : null}
        {history.hasNextPage ? (
          <div className="class-space-older">
            <button type="button" className="button button--ghost button--small" onClick={loadOlder} disabled={history.isFetchingNextPage}>
              {t("common.load_more")}
            </button>
          </div>
        ) : null}
        {history.isSuccess && messages.length === 0 ? <EmptyState icon="school" title={t("classSpace.empty")} /> : null}
        {messages.map((message, index) => {
          const previous = messages[index - 1];
          return (
            <Fragment key={message.id}>
              {!previous || !sameDay(previous.created_at, message.created_at) ? (
                <div className="day-divider" role="separator">
                  <span>{formatDay(message.created_at)}</span>
                </div>
              ) : null}
              <ClassSpaceMessageItem message={message} onDelete={setDeleting} onReport={setReporting} />
            </Fragment>
          );
        })}
      </div>
      <ErrorText error={remove.error} />
      {reporting ? <ReportDialog base={`/class-spaces/${classId}`} messageId={reporting.id} allowEscalate={false} onClose={() => setReporting(null)} /> : null}
      {deleting ? (
        <ConfirmDialog
          title={t("message.delete_title")}
          message={t("message.delete_confirm")}
          confirmLabel={t("message.delete")}
          danger
          busy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting)}
        />
      ) : null}
    </div>
  );
}
