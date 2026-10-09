import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { AuditEntry, ReportEntry, UserCard } from "../api/types";
import { AuditList } from "../components/AuditList";
import { EmptyState } from "../components/EmptyState";
import { ErrorText } from "../components/ErrorText";
import { Icon } from "../components/Icon";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { TextField } from "../components/Field";
import { useAuth } from "../store/auth";
import { formatDateTime } from "../utils/format";
import { isStaffRole } from "../utils/roles";

type Tab = "reports" | "users" | "messages" | "audit";

interface RevealResult {
  user_id: string;
  username: string;
  display_name: string;
  full_name: string;
  declared_class: string | null;
  status: string;
}

function RevealDialog({ user, reportId, onClose }: { user: UserCard; reportId?: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const reveal = useMutation({ mutationFn: () => api.post<RevealResult>(`/moderation/users/${user.id}/identity`, { reason, report_id: reportId }) });
  return (
    <Modal title={t("moderation.reveal_title", { name: user.display_name })} onClose={onClose}>
      <p className="notice">{t("moderation.reveal_warning")}</p>
      {reveal.data ? (
        <dl className="profile__facts">
          <div>
            <dt>{t("moderation.full_name")}</dt>
            <dd>{reveal.data.full_name}</dd>
          </div>
          <div>
            <dt>{t("auth.username")}</dt>
            <dd>@{reveal.data.username}</dd>
          </div>
          <div>
            <dt>{t("moderation.declared_class")}</dt>
            <dd>{reveal.data.declared_class ?? "—"}</dd>
          </div>
          <div>
            <dt>{t("moderation.account_status")}</dt>
            <dd>{reveal.data.status}</dd>
          </div>
        </dl>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            reveal.mutate();
          }}
        >
          <TextField label={t("moderation.reason")} hint={t("moderation.reason_hint")} value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={300} required data-autofocus />
          <ErrorText error={reveal.error} />
          <button type="submit" className="button button--danger" disabled={reveal.isPending || reason.trim().length < 10}>
            {t("moderation.reveal")}
          </button>
        </form>
      )}
    </Modal>
  );
}

function ReportsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<"open" | "resolved" | "dismissed">("open");
  const [selected, setSelected] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [reveal, setReveal] = useState<UserCard | null>(null);
  const list = useQuery({ queryKey: ["mod-reports", status], queryFn: () => api.get<ReportEntry[]>("/moderation/reports", { status }) });
  const detail = useQuery({ queryKey: ["mod-report", selected], queryFn: () => api.get<ReportEntry>(`/moderation/reports/${selected}`), enabled: Boolean(selected) });
  const resolve = useMutation({
    mutationFn: (resolution: "resolved" | "dismissed") => api.post(`/moderation/reports/${selected}/resolve`, { resolution, note }),
    onSuccess: async () => {
      setSelected(null);
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["mod-reports"] });
    },
  });
  return (
    <div className="panel panel--split">
      <div>
        <div className="tabs" role="tablist">
          {(["open", "resolved", "dismissed"] as const).map((value) => (
            <button key={value} type="button" role="tab" aria-selected={status === value} className={status === value ? "is-active" : ""} onClick={() => setStatus(value)}>
              {t(`moderation.status_${value}`)}
            </button>
          ))}
        </div>
        {(list.data ?? []).length === 0 ? <EmptyState icon="flag" title={t("moderation.no_reports")} /> : null}
        <ul className="list">
          {(list.data ?? []).map((report) => (
            <li key={report.id}>
              <button type="button" className={`list__item list__item--stack${selected === report.id ? " is-active" : ""}`} onClick={() => setSelected(report.id)}>
                <strong>{t(`report.reasons.${report.reason}`)}</strong>
                <span className="muted">
                  {report.target?.display_name} · {formatDateTime(report.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        {detail.data ? (
          <article className="report">
            <header>
              <strong>{t(`report.reasons.${detail.data.reason}`)}</strong> <span className="muted">{formatDateTime(detail.data.created_at)}</span>
            </header>
            <p className="muted">
              {t("moderation.reported_user")}: {detail.data.target?.display_name} (@{detail.data.target?.username}) · {t("moderation.reporter")}: {detail.data.reporter?.display_name}
            </p>
            {detail.data.details ? <p>{detail.data.details}</p> : null}
            <ol className="report__context">
              {(detail.data.context ?? []).map((item) => (
                <li key={item.id} className={item.reported ? "is-reported" : ""}>
                  <strong>{item.author?.display_name}</strong> {item.deleted ? <em>{t("message.deleted")}</em> : item.content}
                </li>
              ))}
            </ol>
            {detail.data.target ? (
              <button type="button" className="button button--outline" onClick={() => setReveal(detail.data?.target ?? null)}>
                <Icon name="eye" /> {t("moderation.reveal")}
              </button>
            ) : null}
            {detail.data.status === "open" ? (
              <>
                <TextField label={t("moderation.note")} value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} />
                <ErrorText error={resolve.error} />
                <div className="button-row">
                  <button type="button" className="button button--primary" onClick={() => resolve.mutate("resolved")}>
                    {t("moderation.resolve")}
                  </button>
                  <button type="button" className="button button--ghost" onClick={() => resolve.mutate("dismissed")}>
                    {t("moderation.dismiss")}
                  </button>
                </div>
              </>
            ) : null}
          </article>
        ) : (
          <p className="muted">{t("moderation.select_report")}</p>
        )}
      </div>
      {reveal ? <RevealDialog user={reveal} reportId={selected ?? undefined} onClose={() => setReveal(null)} /> : null}
    </div>
  );
}

function UsersTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [reveal, setReveal] = useState<UserCard | null>(null);
  const [target, setTarget] = useState<{ user: UserCard & { status: string }; next: "active" | "suspended" } | null>(null);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();
  const results = useQuery({
    queryKey: ["mod-users", submitted],
    queryFn: () => api.get<(UserCard & { status: string; platform_role: string })[]>("/moderation/users/lookup", { q: submitted }),
    enabled: submitted.length >= 2,
  });
  const change = useMutation({
    mutationFn: () => api.post(`/moderation/users/${target?.user.id}/status`, { status: target?.next, reason }),
    onSuccess: async () => {
      setTarget(null);
      setReason("");
      await queryClient.invalidateQueries({ queryKey: ["mod-users"] });
    },
  });
  return (
    <div className="panel">
      <form
        className="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <TextField label={t("moderation.lookup")} hint={t("moderation.lookup_hint")} value={query} onChange={(event) => setQuery(event.target.value)} />
        <button type="submit" className="button button--primary" disabled={query.trim().length < 2}>
          {t("search.title")}
        </button>
      </form>
      <ul className="people">
        {(results.data ?? []).map((user) => (
          <li key={user.id}>
            <span className="people__main">
              <span>
                <strong>{user.display_name}</strong>
                <span className="muted">
                  @{user.username} · {user.status} · {user.id}
                </span>
              </span>
            </span>
            <button type="button" className="button button--small" onClick={() => setReveal(user)}>
              {t("moderation.reveal")}
            </button>
            {isAdmin && !isStaffRole(user.platform_role) ? (
              <button type="button" className="button button--small button--danger-ghost" onClick={() => setTarget({ user, next: user.status === "suspended" ? "active" : "suspended" })}>
                {user.status === "suspended" ? t("moderation.restore") : t("moderation.suspend")}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {reveal ? <RevealDialog user={reveal} onClose={() => setReveal(null)} /> : null}
      {target ? (
        <Modal title={target.next === "suspended" ? t("moderation.suspend") : t("moderation.restore")} onClose={() => setTarget(null)}>
          <TextField label={t("moderation.reason")} hint={t("moderation.reason_hint")} value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={300} />
          <ErrorText error={change.error} />
          <button type="button" className="button button--danger" disabled={reason.trim().length < 10 || change.isPending} onClick={() => change.mutate()}>
            {t("common.confirm")}
          </button>
        </Modal>
      ) : null}
    </div>
  );
}

function MessagesTab() {
  const { t } = useTranslation();
  const [messageId, setMessageId] = useState("");
  const [reason, setReason] = useState("");
  const lookup = useMutation({
    mutationFn: () => api.post<{ scope: string; context: NonNullable<ReportEntry["context"]> }>("/moderation/messages/lookup", { message_id: messageId.trim(), reason }),
  });
  return (
    <div className="panel">
      <p className="notice">{t("moderation.message_notice")}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          lookup.mutate();
        }}
      >
        <TextField label={t("moderation.message_id")} value={messageId} onChange={(event) => setMessageId(event.target.value)} inputMode="numeric" />
        <TextField label={t("moderation.reason")} hint={t("moderation.reason_hint")} value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} maxLength={300} />
        <ErrorText error={lookup.error} />
        <button type="submit" className="button button--primary" disabled={lookup.isPending || !/^\d+$/.test(messageId.trim()) || reason.trim().length < 10}>
          {t("moderation.view_message")}
        </button>
      </form>
      {lookup.data ? (
        <ol className="report__context">
          {lookup.data.context.map((item) => (
            <li key={item.id} className={item.reported ? "is-reported" : ""}>
              <strong>{item.author?.display_name}</strong> {item.deleted ? <em>{t("message.deleted")}</em> : item.content}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function AuditTab() {
  const { t } = useTranslation();
  const log = useInfiniteQuery({
    queryKey: ["mod-audit"],
    queryFn: ({ pageParam }) => api.get<{ entries: AuditEntry[]; has_more: boolean }>("/moderation/audit", { before: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.has_more ? last.entries.at(-1)?.id : undefined),
  });
  const entries = log.data?.pages.flatMap((page) => page.entries) ?? [];
  if (entries.length === 0) {
    return <EmptyState icon="shield" title={t("audit.empty")} />;
  }
  return (
    <div className="panel">
      <div className="table-scroll">
        <AuditList entries={entries} />
      </div>
      {log.hasNextPage ? (
        <button type="button" className="button button--outline" onClick={() => void log.fetchNextPage()}>
          {t("common.load_more")}
        </button>
      ) : null}
    </div>
  );
}

export function ModerationPage() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me);
  const isAdmin = me?.platform_role === "school_admin";
  const [tab, setTab] = useState<Tab>("reports");
  const tabs: Tab[] = isAdmin ? ["reports", "users", "messages", "audit"] : ["reports", "users", "messages"];
  if (!me || !isStaffRole(me.platform_role)) {
    return <EmptyState icon="warning" title={t("errors.not_found")} />;
  }
  return (
    <>
      <PageHeader title={t("moderation.title")} />
      <div className="page">
        <p className="notice">
          <Icon name="shield" size={16} /> {t("moderation.logged_notice")}
        </p>
        <div className="tabs" role="tablist">
          {tabs.map((value) => (
            <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>
              {t(`moderation.tab_${value}`)}
            </button>
          ))}
        </div>
        {tab === "reports" ? <ReportsTab /> : null}
        {tab === "users" ? <UsersTab isAdmin={isAdmin} /> : null}
        {tab === "messages" ? <MessagesTab /> : null}
        {tab === "audit" && isAdmin ? <AuditTab /> : null}
      </div>
    </>
  );
}
