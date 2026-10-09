import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useDokMessages } from "../../api/hooks";
import { formatDay, sameDay } from "../../utils/format";
import { EmptyState, Spinner } from "../EmptyState";
import { errorMessage } from "../ErrorText";
import { DokMessageItem } from "./DokMessageItem";

const READ_DELAY_MS = 500;

export function DokMessageList({ threadId, unread }: { threadId: string; unread: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const history = useDokMessages(threadId);
  const scroller = useRef<HTMLDivElement>(null);
  const anchor = useRef<number | null>(null);
  const messages = useMemo(() => [...(history.data?.pages ?? [])].reverse().flatMap((page) => page.messages), [history.data]);
  const newestId = messages.at(-1)?.id ?? null;
  const oldestId = messages[0]?.id ?? null;

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
      void api
        .post(`/dok/threads/${threadId}/read`, { message_id: newestId })
        .then(() => Promise.all([queryClient.invalidateQueries({ queryKey: ["dok", "inbox"] }), queryClient.invalidateQueries({ queryKey: ["notifications"] })]));
    }, READ_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [unread, newestId, threadId, queryClient]);

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
          <div className="dok-older">
            <button type="button" className="button button--ghost button--small" onClick={loadOlder} disabled={history.isFetchingNextPage}>
              {t("common.load_more")}
            </button>
          </div>
        ) : null}
        {history.isSuccess && messages.length === 0 ? <EmptyState icon="megaphone" title={t("dok.empty_thread")} /> : null}
        {messages.map((message, index) => {
          const previous = messages[index - 1];
          return (
            <Fragment key={message.id}>
              {!previous || !sameDay(previous.created_at, message.created_at) ? (
                <div className="day-divider" role="separator">
                  <span>{formatDay(message.created_at)}</span>
                </div>
              ) : null}
              <DokMessageItem message={message} />
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
