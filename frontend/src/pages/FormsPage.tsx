import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { useForms } from "../api/hooks";
import type { FormSummary } from "../api/types";
import { EmptyState, Spinner } from "../components/EmptyState";
import { ErrorText } from "../components/ErrorText";
import { FormEditorDialog } from "../components/forms/FormEditorDialog";
import { FormManageActions } from "../components/forms/FormManageActions";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useAuth } from "../store/auth";
import { formatDate } from "../utils/format";
import { creatorLabel, targetText } from "../utils/forms";
import { canCreateForms } from "../utils/roles";

function FormMeta({ form }: { form: FormSummary }) {
  const { t } = useTranslation();
  return (
    <span className="forms__meta">
      <span>{targetText(t, form.target)}</span>
      <span>{creatorLabel(t, form.creator_role)}</span>
      <span>{formatDate(form.created_at)}</span>
    </span>
  );
}

function FormSection({ title, items, children }: { title: string; items: FormSummary[]; children: (form: FormSummary) => ReactNode }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="forms__section" aria-label={title}>
      <h2>{title}</h2>
      <ul className="forms__list">
        {items.map((form) => (
          <li key={form.id} className="forms__item">
            <div className="forms__main">
              <Link to={`/app/forms/${form.id}`} className="forms__title">
                {form.title}
              </Link>
              <FormMeta form={form} />
            </div>
            {children(form)}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function FormsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const role = useAuth((state) => state.me?.platform_role);
  const forms = useForms();
  const [creating, setCreating] = useState(false);
  const allowed = canCreateForms(role);
  const items = forms.data?.items ?? [];
  const toFill = items.filter((form) => form.can_fill);
  const finished = items.filter((form) => form.targeted && !form.can_fill);
  const managed = items.filter((form) => form.can_view_results);
  const empty = !forms.isLoading && !forms.isError && toFill.length === 0 && finished.length === 0 && managed.length === 0;
  return (
    <>
      <PageHeader title={t("forms.title")} lead={<Icon name="clipboard" />}>
        {allowed ? (
          <button type="button" className="button button--small button--primary" onClick={() => setCreating(true)}>
            <Icon name="plus" size={16} /> {t("forms.new")}
          </button>
        ) : null}
      </PageHeader>
      <div className="page">
        <div className="forms">
          <p className="muted">{t("forms.intro")}</p>
          {forms.isLoading ? <Spinner label={t("common.loading")} /> : null}
          {forms.isError ? <ErrorText error={forms.error} /> : null}
          <FormSection title={t("forms.section_fill")} items={toFill}>
            {(form) => (
              <Link to={`/app/forms/${form.id}`} className="button button--small button--primary">
                {t("forms.fill")}
              </Link>
            )}
          </FormSection>
          <FormSection title={t("forms.section_done")} items={finished}>
            {(form) => (
              <>
                <span className={`forms__badge forms__badge--${form.submitted ? "done" : "closed"}`}>
                  {form.submitted ? t("forms.status_submitted") : t("forms.status_closed")}
                </span>
                <Link to={`/app/forms/${form.id}`} className="button button--small button--ghost">
                  {t("forms.view")}
                </Link>
              </>
            )}
          </FormSection>
          <FormSection title={t("forms.section_manage")} items={managed}>
            {(form) => (
              <div className="forms__actions">
                <span className={`forms__badge forms__badge--${form.status}`}>{t(`forms.status_${form.status}`)}</span>
                <span className="muted">{t("forms.response_count", { count: form.response_count ?? 0 })}</span>
                <Link to={`/app/forms/${form.id}/results`} className="button button--small button--outline">
                  {t("forms.results")}
                </Link>
                <FormManageActions form={form} />
              </div>
            )}
          </FormSection>
          {empty ? (
            <EmptyState icon="clipboard" title={t("forms.empty_title")}>
              {allowed ? t("forms.empty_staff") : t("forms.empty")}
            </EmptyState>
          ) : null}
        </div>
      </div>
      {creating ? <FormEditorDialog onClose={() => setCreating(false)} onCreated={(form) => navigate(`/app/forms/${form.id}/results`)} /> : null}
    </>
  );
}
