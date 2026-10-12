import { useTranslation } from "react-i18next";

import type { FormQuestion } from "../../api/types";
import { FORM_LIMITS, describeProblem, type AnswerEntry, type Problem } from "../../utils/forms";
import { TextAreaField, TextField } from "../Field";

interface FormQuestionFieldProps {
  question: FormQuestion;
  entry: AnswerEntry;
  problem?: Problem;
  disabled?: boolean;
  onChange: (entry: AnswerEntry) => void;
}

export function FormQuestionField({ question, entry, problem, disabled, onChange }: FormQuestionFieldProps) {
  const { t } = useTranslation();
  const error = problem ? describeProblem(t, problem) : null;
  const hint = question.required ? t("forms.required") : undefined;
  if (question.type === "short_text") {
    return (
      <TextField
        label={question.label}
        hint={hint}
        error={error}
        value={entry.text}
        maxLength={FORM_LIMITS.shortText}
        disabled={disabled}
        onChange={(event) => onChange({ ...entry, text: event.target.value })}
      />
    );
  }
  if (question.type === "long_text") {
    return (
      <TextAreaField
        label={question.label}
        hint={hint}
        error={error}
        rows={5}
        value={entry.text}
        maxLength={FORM_LIMITS.longText}
        disabled={disabled}
        onChange={(event) => onChange({ ...entry, text: event.target.value })}
      />
    );
  }
  const single = question.type === "single_choice";
  const choose = (optionId: string, checked: boolean) => {
    if (single) {
      onChange({ ...entry, options: checked ? [optionId] : [] });
    } else {
      onChange({ ...entry, options: checked ? [...entry.options, optionId] : entry.options.filter((value) => value !== optionId) });
    }
  };
  return (
    <fieldset className="forms-choice" disabled={disabled}>
      <legend>{question.label}</legend>
      {hint ? <p className="field__hint">{hint}</p> : null}
      {question.options.map((option) => (
        <label key={option.id} className="check">
          <input
            type={single ? "radio" : "checkbox"}
            name={`question-${question.id}`}
            value={option.id}
            checked={entry.options.includes(option.id)}
            onChange={(event) => choose(option.id, event.target.checked)}
          />
          <span>{option.label}</span>
        </label>
      ))}
      {single && !question.required && entry.options.length > 0 ? (
        <button type="button" className="button button--small button--ghost" onClick={() => onChange({ ...entry, options: [] })}>
          {t("forms.clear_choice")}
        </button>
      ) : null}
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
