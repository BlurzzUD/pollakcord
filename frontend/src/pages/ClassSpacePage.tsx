import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useClassSpace } from "../api/hooks";
import { ClassSpaceComposer } from "../components/classspace/ClassSpaceComposer";
import { ClassSpaceMembersDialog } from "../components/classspace/ClassSpaceMembersDialog";
import { ClassSpaceMessageList } from "../components/classspace/ClassSpaceMessageList";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../store/auth";
import { useClassSpaceUi } from "../store/classSpace";
import { anonymousLabel } from "../utils/classSpace";

export function ClassSpacePage() {
  const { t } = useTranslation();
  const classCode = useAuth((state) => state.me?.class_code);
  const space = useClassSpace();
  const reopen = useClassSpaceUi((state) => state.reopen);
  const [showMembers, setShowMembers] = useState(false);
  const state = space.data;

  if (!classCode) {
    return (
      <>
        <PageHeader title={t("nav.class_space")} lead={<Icon name="school" />} />
        <div className="page">
          <p className="notice">
            {t("classSpace.no_class_text")} <Link to="/app/settings/account">{t("classSpace.no_class_link")}</Link>
          </p>
          <EmptyState icon="school" title={t("classSpace.no_class_title")} />
        </div>
      </>
    );
  }
  if (space.isError || (state && !state.class)) {
    return (
      <>
        <PageHeader title={t("nav.class_space")} lead={<Icon name="school" />} />
        <EmptyState icon="warning" title={t("classSpace.unavailable")} />
      </>
    );
  }
  if (!state || !state.class) {
    return <PageHeader title={t("common.loading")} />;
  }
  const school = state.class;
  const title = t("classSpace.page_title", { code: school.code });

  if (!state.member) {
    return (
      <>
        <PageHeader title={title} lead={<Icon name="school" />} />
        <div className="page">
          <section className="card" aria-labelledby="class-space-pending">
            <header className="card__head">
              <h3 id="class-space-pending">{t("classSpace.pending_title")}</h3>
            </header>
            <p>{t("classSpace.pending_text")}</p>
            <button type="button" className="button button--primary" onClick={reopen}>
              {t("classSpace.pending_action")}
            </button>
          </section>
        </div>
      </>
    );
  }
  return (
    <>
      <PageHeader title={title} lead={<Icon name="school" />}>
        <button type="button" className="button button--ghost button--small" onClick={() => setShowMembers(true)}>
          <Icon name="users" size={18} /> {t("classSpace.members_button", { count: state.members ?? 0 })}
        </button>
      </PageHeader>
      <p className="class-space-banner">
        <Icon name="shield" size={16} /> {state.show_username ? t("classSpace.notice_visible") : t("classSpace.notice_hidden", { label: anonymousLabel(t, state.alias) })}
      </p>
      <ClassSpaceMessageList key={`list-${school.id}`} classId={school.id} unread={state.unread} />
      <ClassSpaceComposer key={`composer-${school.id}`} classId={school.id} />
      {showMembers ? <ClassSpaceMembersDialog classId={school.id} code={school.code} onClose={() => setShowMembers(false)} /> : null}
    </>
  );
}
