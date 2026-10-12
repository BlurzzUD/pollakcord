import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { useForm } from "../api/hooks";
import type { FormAnswerPayload, FormDetail, FormSubmission } from "../api/types";
import { EmptyState, Spinner } from "../components/EmptyState";
import { ErrorText } from "../components/ErrorText";
import { FormQuestionField } from "../components/forms/FormQuestionField";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useUi } from "../store/ui";
import { formatDateTime } from "../utils/format";
import { answerProblems, buildAnswers, creatorLabel, emptyAnswers, targetText, type AnswerState, type Problem } from "../utils/forms";

function FormFill({ form }: { form: FormDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const [answers, setAnswers] = useState<AnswerState>(() => emptyAnswers(form.questions));
  const [problems, setProblems] = useState<Record<string, Problem>>({});
  const submit = useMutation({
    mutationFn: (payload: FormAnswerPayload[]) => api.post<FormSubmission>(`/forms/${form.id}/responses`, { answers: payload }),
    onSuccess: (result) => {
      queryClient.setQueryData<FormDetail>(["forms", "detail", form.id], (current) =>
        current ? { ...current, submitted: true, submitted_at: result.submitted_at, can_fill: false } : current,
      );
      void queryClient.invalidateQueries({ queryKey: ["forms", "list"] });
      push("success", t("forms.submitted_toast"));
    },
    onError: (failure) => {
      if (failure instanceof ApiError && (failure.code === "form_closed" || failure.code === "form_already_submitted")) {
        void queryClient.invalidateQueries({ queryKey: ["forms"] });
      }
    },
  });

  const send = () => {
    const found = answerProblems(form.questions, answers);
    setProblems(found);
    if (Object.keys(found).length === 0) {
      submit.mutate(buildAnswers(form.questions, answers));
    }
  };

  const change = (questionId: string, entry: AnswerState[string]) => {
    setAnswers((current) => ({ ...current, [questionId]: entry }));
    setProblems((current) => {
      const next = { ...current };
      delete next[questionId];
      return next;
    });
    submit.reset();
  };

  let notice: string | null = null;
  if (form.submitted) {
    notice = t("forms.already_submitted", { date: form.submitted_at ? formatDateTime(form.submitted_at) : "" });
  } else if (form.status === "closed") {
    notice = t("forms.closed_notice");
  } else if (!form.targeted) {
    notice = t("forms.not_in_audience");
  }

  return (
    <div className="forms-fill">
      <Link to="/app/forms" className="forms__back">
        <Icon name="arrowLeft" size={16} /> {t("forms.back_to_list")}
      </Link>
      <section className="card">
        <div className="forms__meta">
          <span>{targetText(t, form.target)}</span>
          <span>{creatorLabel(t, form.creator_role)}</span>
          <span className={`forms__badge forms__badge--${form.status}`}>{t(`forms.status_${form.status}`)}</span>
        </div>
        {form.description ? <p className="forms__description">{form.description}</p> : null}
      </section>
      {notice ? (
        <p className="notice" role="status">
          {notice}
        </p>
      ) : null}
      {form.can_fill ? (
        <form
          className="card forms-fill__questions"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            send();
          }}
        >
          {form.questions.map((question) => (
            <FormQuestionField
              key={question.id}
              question={question}
              entry={answers[question.id] ?? { text: "", options: [] }}
              problem={problems[question.id]}
              disabled={submit.isPending}
              onChange={(entry) => change(question.id, entry)}
            />
          ))}
          <ErrorText error={submit.error} />
          <button type="submit" className="button button--primary" disabled={submit.isPending}>
            {t("forms.submit")}
          </button>
        </form>
      ) : null}
    </div>
  );
}

export function FormPage() {
  const { t } = useTranslation();
  const { formId } = useParams();
  const form = useForm(formId);
  return (
    <>
      <PageHeader title={form.data?.title ?? t("forms.title")} lead={<Icon name="clipboard" />}>
        {form.data?.can_view_results ? (
          <Link to={`/app/forms/${form.data.id}/results`} className="button button--small button--outline">
            {t("forms.results")}
          </Link>
        ) : null}
      </PageHeader>
      <div className="page">
        {form.isLoading ? <Spinner label={t("common.loading")} /> : null}
        {form.isError ? (
          <EmptyState icon="clipboard" title={t("forms.unavailable_title")}>
            {t("forms.unavailable")}
          </EmptyState>
        ) : null}
        {form.data ? <FormFill key={form.data.id} form={form.data} /> : null}
      </div>
    </>
  );
}
