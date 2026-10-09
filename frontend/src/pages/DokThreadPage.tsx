import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { useDokInbox } from "../api/hooks";
import { DokComposer } from "../components/dok/DokComposer";
import { DokMessageList } from "../components/dok/DokMessageList";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { threadLabel, threadTargetValue } from "../utils/dok";

export function DokThreadPage() {
  const { t } = useTranslation();
  const { threadId = "" } = useParams();
  const navigate = useNavigate();
  const inbox = useDokInbox();
  const thread = inbox.data?.threads.find((item) => item.id === threadId);

  if (inbox.isError || (inbox.isSuccess && !thread)) {
    return (
      <>
        <PageHeader title={t("dok.unavailable")} />
        <EmptyState icon="warning" title={t("dok.unavailable")} />
      </>
    );
  }
  if (!thread || !inbox.data) {
    return <PageHeader title={t("common.loading")} />;
  }
  return (
    <>
      <PageHeader title={threadLabel(t, thread)} lead={<Icon name="megaphone" />} />
      <p className="dok-banner">
        <Icon name="shield" size={16} /> {t("dok.anonymous_notice")}
      </p>
      <DokMessageList key={`list-${thread.id}`} threadId={thread.id} unread={thread.unread} />
      {thread.can_send ? (
        <DokComposer key={`composer-${thread.id}`} targets={inbox.data.send.targets} preferred={threadTargetValue(thread)} onSent={(message) => {
            if (message.thread_id !== thread.id) {
              navigate(`/app/dok/${message.thread_id}`);
            }
          }}
        />
      ) : null}
    </>
  );
}
