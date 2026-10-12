import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useForm, useFormResults } from "../api/hooks";
import type { FormQuestion, FormResultResponse, FormResultSummary } from "../api/types";
import { EmptyState, Spinner } from "../components/EmptyState";
import { ErrorText } from "../components/ErrorText";
import { FormManageActions } from "../components/forms/FormManageActions";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { answerText, isChoice, percentage, targetText } from "../utils/forms";

function Respondent({ response }: { response: FormResultResponse }) {
  const { t } = useTranslation();
  if (!response.user) {
    return <span className="forms-answers__who">{t("forms.deleted_user")}</span>;
  }
  return (
    <span className="forms-answers__who">
      <strong>{response.user.display_name}</strong> @{response.user.username}
    </span>
  );
}

function ChoiceResult({ summary, total }: { summary: FormResultSummary; total: number }) {
  return (
    <ul className="forms-result__options">
      {summary.options.map((option) => {
        const share = percentage(option.count, summary.answered > 0 ? summary.answered : total);
        return (
          <li key={option.id} className="forms-result__option">
            <div className="forms-result__line">
              <span>{option.label}</span>
              <span className="muted">
                {option.count} ({share}%)
              </span>
            </div>
            <div className="forms-bar" aria-hidden="true">
              <span style={{ width: `${share}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function TextResult({ question, responses }: { question: FormQuestion; responses: FormResultResponse[] }) {
  const { t } = useTranslation();
  const rows = responses.filter((response) => question.id in response.answers);
  if (rows.length === 0) {
    return <p className="muted">{t("forms.no_text_answers")}</p>;
  }
  return (
    <ul className="forms-answers">
      {rows.map((response) => {
        const text = answerText(response.answers[question.id]);
        return (
          <li key={response.id} className="forms-answers__item">
            <p className="forms-answers__text">{text ?? t("forms.unreadable")}</p>
            <Respondent response={response} />
          </li>
        );
      })}
    </ul>
  );
}

export function FormResultsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { formId } = useParams();
  const form = useForm(formId);
  const allowed = Boolean(form.data?.can_view_results);
  const results = useFormResults(formId, allowed);
  const pages = results.data?.pages ?? [];
  const total = pages[0]?.total ?? 0;
  const summaries = pages[0]?.summary ?? [];
  const responses = pages.flatMap((page) => page.responses);

  if (form.isLoading) {
    return (
      <>
        <PageHeader title={t("forms.results")} lead={<Icon name="clipboard" />} />
        <div className="page">
          <Spinner label={t("common.loading")} />
        </div>
      </>
    );
  }

  if (form.isError || !form.data || !form.data.can_view_results) {
    return (
      <>
        <PageHeader title={t("forms.results")} lead={<Icon name="clipboard" />} />
        <div className="page">
          <EmptyState icon="clipboard" title={t("forms.results_forbidden_title")}>
            {t("forms.results_forbidden")}
          </EmptyState>
        </div>
      </>
    );
  }

  const current = form.data;
  return (
    <>
      <PageHeader title={t("forms.results_for", { title: current.title })} lead={<Icon name="clipboard" />} />
      <div className="page">
        <div className="forms">
          <Link to="/app/forms" className="forms__back">
            <Icon name="arrowLeft" size={16} /> {t("forms.back_to_list")}
          </Link>
          <section className="card forms-result__head">
            <div className="forms__meta">
              <span>{targetText(t, current.target)}</span>
              <span className={`forms__badge forms__badge--${current.status}`}>{t(`forms.status_${current.status}`)}</span>
              <span>{t("forms.response_count", { count: total })}</span>
            </div>
            <div className="forms__actions">
              <Link to={`/app/forms/${current.id}`} className="button button--small button--ghost">
                {t("forms.view_form")}
              </Link>
              <FormManageActions form={current} onDeleted={() => navigate("/app/forms")} />
            </div>
          </section>
          <p className="notice">{t("forms.staff_notice")}</p>
          {results.isLoading ? <Spinner label={t("common.loading")} /> : null}
          {results.isError ? <ErrorText error={results.error} /> : null}
          {total === 0 && !results.isLoading && !results.isError ? <EmptyState icon="clipboard" title={t("forms.no_responses")} /> : null}
          {total > 0
            ? current.questions.map((question, index) => {
                const summary = summaries.find((entry) => entry.question_id === question.id);
                return (
                  <section key={question.id} className="card forms-result">
                    <h2>
                      {index + 1}. {question.label}
                    </h2>
                    <p className="forms__meta">
                      <span>{t(`forms.type_${question.type}`)}</span>
                      <span>{t("forms.answered_count", { count: summary?.answered ?? 0 })}</span>
                    </p>
                    {isChoice(question.type) && summary ? <ChoiceResult summary={summary} total={total} /> : <TextResult question={question} responses={responses} />}
                  </section>
                );
              })
            : null}
          {results.hasNextPage ? (
            <div className="forms__more">
              <p className="muted">{t("forms.loaded_count", { loaded: responses.length, total })}</p>
              <button type="button" className="button button--outline" onClick={() => void results.fetchNextPage()} disabled={results.isFetchingNextPage}>
                {t("common.load_more")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
