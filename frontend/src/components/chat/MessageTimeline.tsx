import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { useMeta } from "../../api/hooks";
import type { Message } from "../../api/types";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { useUi } from "../../store/ui";
import { compareIds, formatDay, sameDay } from "../../utils/format";
import { ConfirmDialog } from "../ConfirmDialog";
import { EmptyState, Spinner } from "../EmptyState";
import { errorMessage } from "../ErrorText";
import { Icon } from "../Icon";
import { Composer, type MentionCandidate } from "./Composer";
import { MessageItem } from "./MessageItem";
import { ReportDialog } from "./ReportDialog";
import { useTimeline, type Scope } from "./useTimeline";

interface MessageTimelineProps {
  scope: Scope;
  id: string;
  serverId?: string;
  names: Record<string, string>;
  candidates: MentionCandidate[];
  placeholder: string;
  canSend: boolean;
  sendBlockedReason?: string | null;
  canReact: boolean;
  canModerate: boolean;
  allowEscalate: boolean;
}

const GROUP_WINDOW_MS = 7 * 60 * 1000;
const BOTTOM_THRESHOLD = 90;

export function MessageTimeline(props: MessageTimelineProps) {
  const { scope, id, serverId, names, candidates, placeholder, canSend, sendBlockedReason, canReact, canModerate, allowEscalate } = props;
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const meId = useAuth((state) => state.me?.id);
  const meta = useMeta();
  const typing = useLive((state) => state.typing[`${scope}:${id}`]);
  const [tick, setTick] = useState(0);
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [reporting, setReporting] = useState<Message | null>(null);
  const [deleting, setDeleting] = useState<Message | null>(null);
  const [newBelow, setNewBelow] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const readTimer = useRef<number | null>(null);
  const dividerAfter = useRef<string | null | undefined>(undefined);
  const previousHeight = useRef(0);

  const scheduleRead = useCallback(() => {
    if (readTimer.current !== null) {
      window.clearTimeout(readTimer.current);
    }
    readTimer.current = window.setTimeout(() => {
      readTimer.current = null;
      if (document.visibilityState === "visible" && atBottom.current) {
        void markReadRef.current();
      }
    }, 500);
  }, []);

  const timeline = useTimeline(scope, id, scheduleRead);
  const markReadRef = useRef(timeline.markRead);
  markReadRef.current = async () => {
    await timeline.markRead();
    await queryClient.invalidateQueries({ queryKey: scope === "dm" ? ["dms"] : ["server", serverId] });
  };

  useEffect(() => {
    dividerAfter.current = undefined;
    setReplyTo(null);
    atBottom.current = true;
  }, [id]);

  useEffect(() => {
    if (timeline.status === "ready" && dividerAfter.current === undefined) {
      dividerAfter.current = timeline.lastRead;
      scheduleRead();
    }
  }, [timeline.status, timeline.lastRead, scheduleRead]);

  useEffect(() => {
    const interval = window.setInterval(() => setTick((value) => value + 1), 1500);
    return () => window.clearInterval(interval);
  }, []);

  useLayoutEffect(() => {
    const element = container.current;
    if (!element) {
      return;
    }
    const last = timeline.messages.at(-1);
    if (previousHeight.current && element.scrollTop < 40 && !atBottom.current) {
      element.scrollTop += element.scrollHeight - previousHeight.current;
    } else if (atBottom.current || last?.author?.id === meId) {
      element.scrollTop = element.scrollHeight;
      setNewBelow(false);
    } else if (last) {
      setNewBelow(true);
    }
    previousHeight.current = element.scrollHeight;
  }, [timeline.messages, meId]);

  const onScroll = () => {
    const element = container.current;
    if (!element) {
      return;
    }
    atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < BOTTOM_THRESHOLD;
    if (atBottom.current) {
      setNewBelow(false);
      scheduleRead();
    }
    if (element.scrollTop < 120 && timeline.hasMore && !timeline.loadingOlder) {
      previousHeight.current = element.scrollHeight;
      void timeline.loadOlder();
    }
  };

  const jumpToBottom = () => {
    const element = container.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
      atBottom.current = true;
      setNewBelow(false);
      scheduleRead();
    }
  };

  const guard = async (action: () => Promise<unknown>) => {
    try {
      await action();
    } catch (failure) {
      push("error", errorMessage(t, failure));
    }
  };

  const typingNames = useMemo(() => {
    void tick;
    const now = Date.now();
    return Object.entries(typing ?? {})
      .filter(([userId, expires]) => userId !== meId && expires > now)
      .map(([userId]) => names[userId] ?? t("message.unknown_user"));
  }, [typing, names, meId, tick, t]);

  const items = timeline.messages;
  const reactions = meta.data?.reactions ?? [];

  return (
    <div className="timeline">
      <div className="timeline__scroll" ref={container} onScroll={onScroll} role="log" aria-live="polite" aria-relevant="additions" aria-label={t("a11y.messages_region")}>
        {timeline.status === "loading" ? <Spinner label={t("common.loading")} /> : null}
        {timeline.status === "error" ? <p className="form-error" role="alert">{errorMessage(t, timeline.error)}</p> : null}
        {timeline.loadingOlder ? <Spinner label={t("common.loading")} /> : null}
        {timeline.status === "ready" && items.length === 0 ? (
          <EmptyState icon="hash" title={t("message.empty_title")}>
            {t("message.empty_text")}
          </EmptyState>
        ) : null}
        {items.map((message, index) => {
          const previous = items[index - 1];
          const newDay = !previous || !sameDay(previous.created_at, message.created_at);
          const compact =
            !newDay &&
            !!previous &&
            !previous.deleted &&
            !message.reply_to &&
            previous.author?.id === message.author?.id &&
            new Date(message.created_at).getTime() - new Date(previous.created_at).getTime() < GROUP_WINDOW_MS;
          const unreadStart =
            dividerAfter.current !== undefined &&
            message.author?.id !== meId &&
            compareIds(message.id, dividerAfter.current ?? "0") > 0 &&
            (!previous || compareIds(previous.id, dividerAfter.current ?? "0") <= 0);
          return (
            <div key={message.id}>
              {newDay ? (
                <div className="day-divider" role="separator">
                  <span>{formatDay(message.created_at)}</span>
                </div>
              ) : null}
              {unreadStart ? (
                <div className="unread-divider" role="separator">
                  <span>{t("message.new_messages")}</span>
                </div>
              ) : null}
              <MessageItem
                message={message}
                compact={compact}
                names={names}
                reactions={reactions}
                canReact={canReact}
                canDelete={canModerate}
                canPin={scope === "channel" && canModerate}
                canReport={true}
                onReply={(target) => setReplyTo(target)}
                onReact={(target, emoji, present) => void guard(() => timeline.react(target.id, emoji, present))}
                onDelete={(target) => setDeleting(target)}
                onPin={(target) => void guard(() => (target.pinned ? api.del(`/channels/${id}/pins/${target.id}`) : api.put(`/channels/${id}/pins/${target.id}`)))}
                onReport={(target) => setReporting(target)}
              />
            </div>
          );
        })}
      </div>
      {newBelow ? (
        <button type="button" className="timeline__jump" onClick={jumpToBottom}>
          <Icon name="chevronDown" size={16} /> {t("message.jump_to_new")}
        </button>
      ) : null}
      <div className="timeline__typing" aria-live="polite">
        {typingNames.length > 0 ? t("message.typing", { count: typingNames.length, names: typingNames.join(", ") }) : ""}
      </div>
      <Composer
        placeholder={placeholder}
        disabledReason={canSend ? null : (sendBlockedReason ?? t("message.cannot_send"))}
        maxLength={meta.data?.limits.message_max_length ?? 4000}
        typingTarget={{ scope, id }}
        replyTo={replyTo}
        onCancelReply={() => setReplyTo(null)}
        onSend={timeline.send}
        candidates={candidates}
      />
      {reporting ? <ReportDialog base={timeline.base} messageId={reporting.id} allowEscalate={allowEscalate} onClose={() => setReporting(null)} /> : null}
      {deleting ? (
        <ConfirmDialog
          title={t("message.delete_title")}
          message={t("message.delete_confirm")}
          confirmLabel={t("message.delete")}
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const target = deleting;
            setDeleting(null);
            void guard(() => timeline.remove(target.id));
          }}
        />
      ) : null}
    </div>
  );
}
