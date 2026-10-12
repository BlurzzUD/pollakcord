import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { FormCreateBody, FormDetail, FormQuestionType, SchoolClass } from "../../api/types";
import { useUi } from "../../store/ui";
import {
  QUESTION_TYPES,
  FORM_LIMITS,
  SCHOOL_TARGET,
  describeProblem,
  draftProblem,
  emptyDraft,
  emptyQuestion,
  isChoice,
  toCreateBody,
  type DraftForm,
  type DraftQuestion,
  type Problem,
} from "../../utils/forms";
import { ErrorText } from "../ErrorText";
import { SelectField, TextAreaField, TextField, Toggle } from "../Field";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

export function FormEditorDialog({ onClose, onCreated }: { onClose: () => void; onCreated?: (form: FormDetail) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const classes = useQuery({ queryKey: ["classes"], queryFn: () => api.get<SchoolClass[]>("/me/classes") });
  const [draft, setDraft] = useState<DraftForm>(emptyDraft);
  const [nextKey, setNextKey] = useState(2);
  const [problem, setProblem] = useState<Problem | null>(null);
  const create = useMutation({
    mutationFn: (body: FormCreateBody) => api.post<FormDetail>("/forms", body),
    onSuccess: (form) => {
      void queryClient.invalidateQueries({ queryKey: ["forms"] });
      push("success", t("forms.created_toast"));
      onCreated?.(form);
      onClose();
    },
  });

  const update = (change: (current: DraftForm) => DraftForm) => {
    setDraft(change);
    setProblem(null);
    create.reset();
  };
  const updateQuestion = (key: number, changes: Partial<DraftQuestion>) =>
    update((current) => ({
      ...current,
      questions: current.questions.map((question) => (question.key === key ? { ...question, ...changes } : question)),
    }));
  const addQuestion = () => {
    update((current) => ({ ...current, questions: [...current.questions, emptyQuestion(nextKey)] }));
    setNextKey((value) => value + 1);
  };
  const removeQuestion = (key: number) => update((current) => ({ ...current, questions: current.questions.filter((question) => question.key !== key) }));
  const changeType = (question: DraftQuestion, type: FormQuestionType) =>
    updateQuestion(question.key, { type, options: isChoice(type) && question.options.length < FORM_LIMITS.optionsMin ? ["", ""] : question.options });
  const setOption = (question: DraftQuestion, index: number, value: string) =>
    updateQuestion(question.key, { options: question.options.map((option, position) => (position === index ? value : option)) });
  const addOption = (question: DraftQuestion) => updateQuestion(question.key, { options: [...question.options, ""] });
  const removeOption = (question: DraftQuestion, index: number) =>
    updateQuestion(question.key, { options: question.options.filter((_, position) => position !== index) });

  const submit = () => {
    const found = draftProblem(draft);
    if (found) {
      setProblem(found);
      return;
    }
    create.mutate(toCreateBody(draft));
  };

  const targets = [
    { value: SCHOOL_TARGET, label: t("forms.target_school") },
    ...(classes.data ?? []).map((school) => ({ value: school.id, label: t("forms.target_class", { code: school.code }) })),
  ];

  return (
    <Modal
      title={t("forms.new")}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="button" className="button button--primary" onClick={submit} disabled={create.isPending}>
            {t("forms.publish")}
          </button>
        </>
      }
    >
      <TextField
        label={t("forms.field_title")}
        value={draft.title}
        maxLength={FORM_LIMITS.title}
        data-autofocus
        onChange={(event) => update((current) => ({ ...current, title: event.target.value }))}
      />
      <TextAreaField
        label={t("forms.field_description")}
        hint={t("forms.field_description_hint")}
        rows={3}
        value={draft.description}
        maxLength={FORM_LIMITS.description}
        onChange={(event) => update((current) => ({ ...current, description: event.target.value }))}
      />
      <SelectField
        label={t("forms.field_target")}
        hint={t("forms.field_target_hint")}
        value={draft.target}
        options={targets}
        onChange={(event) => update((current) => ({ ...current, target: event.target.value }))}
      />
      {draft.questions.map((question, index) => {
        const number = index + 1;
        return (
          <fieldset key={question.key} className="forms-editor__question">
            <legend>{t("forms.question_number", { number })}</legend>
            <SelectField
              label={t("forms.question_type_n", { number })}
              value={question.type}
              options={QUESTION_TYPES.map((type) => ({ value: type, label: t(`forms.type_${type}`) }))}
              onChange={(event) => changeType(question, event.target.value as FormQuestionType)}
            />
            <TextField
              label={t("forms.question_text_n", { number })}
              value={question.label}
              maxLength={FORM_LIMITS.label}
              onChange={(event) => updateQuestion(question.key, { label: event.target.value })}
            />
            {isChoice(question.type) ? (
              <div className="field">
                <p className="forms-editor__options-title">{t("forms.options")}</p>
                <ul className="forms-editor__options">
                  {question.options.map((option, position) => (
                    <li key={position} className="forms-editor__option">
                      <input
                        value={option}
                        maxLength={FORM_LIMITS.optionLabel}
                        placeholder={t("forms.option_placeholder")}
                        aria-label={t("forms.option_label", { question: number, number: position + 1 })}
                        onChange={(event) => setOption(question, position, event.target.value)}
                      />
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => removeOption(question, position)}
                        disabled={question.options.length <= FORM_LIMITS.optionsMin}
                        aria-label={t("forms.remove_option", { question: number, number: position + 1 })}
                      >
                        <Icon name="close" size={16} />
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="button button--small button--ghost"
                  onClick={() => addOption(question)}
                  disabled={question.options.length >= FORM_LIMITS.optionsMax}
                >
                  <Icon name="plus" size={16} /> {t("forms.add_option")}
                </button>
              </div>
            ) : null}
            <Toggle label={t("forms.required")} checked={question.required} onChange={(checked) => updateQuestion(question.key, { required: checked })} />
            <button
              type="button"
              className="button button--small button--danger-ghost"
              onClick={() => removeQuestion(question.key)}
              disabled={draft.questions.length <= 1}
            >
              {t("forms.remove_question", { number })}
            </button>
          </fieldset>
        );
      })}
      <button type="button" className="button button--outline" onClick={addQuestion} disabled={draft.questions.length >= FORM_LIMITS.questions}>
        <Icon name="plus" size={16} /> {t("forms.add_question")}
      </button>
      {problem ? (
        <p className="form-error" role="alert">
          {describeProblem(t, problem)}
        </p>
      ) : null}
      <ErrorText error={create.error} />
    </Modal>
  );
}
