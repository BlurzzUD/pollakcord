import type {
  FormAnswerPayload,
  FormAnswerValue,
  FormCreateBody,
  FormCreatorRole,
  FormQuestion,
  FormQuestionType,
  FormTarget,
} from "../api/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export const FORM_LIMITS = {
  title: 120,
  description: 1000,
  questions: 30,
  label: 200,
  optionsMin: 2,
  optionsMax: 12,
  optionLabel: 100,
  shortText: 200,
  longText: 2000,
} as const;

export const QUESTION_TYPES: FormQuestionType[] = ["short_text", "long_text", "single_choice", "multiple_choice"];
export const SCHOOL_TARGET = "school";

export interface Problem {
  code: string;
  params?: Record<string, number>;
}

export interface DraftQuestion {
  key: number;
  type: FormQuestionType;
  label: string;
  required: boolean;
  options: string[];
}

export interface DraftForm {
  title: string;
  description: string;
  target: string;
  questions: DraftQuestion[];
}

export interface AnswerEntry {
  text: string;
  options: string[];
}

export type AnswerState = Record<string, AnswerEntry>;

export function isChoice(type: FormQuestionType): boolean {
  return type === "single_choice" || type === "multiple_choice";
}

export function creatorLabel(t: Translate, role: FormCreatorRole): string {
  return role === "dok_president" ? t("dok.role_president") : t("common.staff");
}

export function targetText(t: Translate, target: FormTarget): string {
  return target.type === "school" ? t("forms.target_school") : t("forms.target_class", { code: target.code ?? "" });
}

export function describeProblem(t: Translate, problem: Problem): string {
  return t(`errors.${problem.code}`, problem.params);
}

function collapse(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function emptyQuestion(key: number, type: FormQuestionType = "short_text"): DraftQuestion {
  return { key, type, label: "", required: false, options: isChoice(type) ? ["", ""] : [] };
}

export function emptyDraft(): DraftForm {
  return { title: "", description: "", target: SCHOOL_TARGET, questions: [emptyQuestion(1)] };
}

export function draftProblem(draft: DraftForm): Problem | null {
  const title = collapse(draft.title);
  if (title === "" || title.length > FORM_LIMITS.title) {
    return { code: "form_title_invalid", params: { max: FORM_LIMITS.title } };
  }
  if (draft.description.trim().length > FORM_LIMITS.description) {
    return { code: "form_description_invalid", params: { max: FORM_LIMITS.description } };
  }
  if (draft.questions.length < 1 || draft.questions.length > FORM_LIMITS.questions) {
    return { code: "form_questions_invalid", params: { max: FORM_LIMITS.questions } };
  }
  for (const question of draft.questions) {
    const label = collapse(question.label);
    if (label === "" || label.length > FORM_LIMITS.label) {
      return { code: "form_question_invalid", params: { max: FORM_LIMITS.label } };
    }
    if (isChoice(question.type)) {
      const options = question.options.map(collapse);
      const distinct = new Set(options.map((option) => option.toLowerCase())).size === options.length;
      const sized = options.length >= FORM_LIMITS.optionsMin && options.length <= FORM_LIMITS.optionsMax;
      const filled = options.every((option) => option !== "" && option.length <= FORM_LIMITS.optionLabel);
      if (!sized || !filled || !distinct) {
        return { code: "form_options_invalid", params: { min: FORM_LIMITS.optionsMin, max: FORM_LIMITS.optionsMax, label_max: FORM_LIMITS.optionLabel } };
      }
    }
  }
  return null;
}

export function toCreateBody(draft: DraftForm): FormCreateBody {
  return {
    title: collapse(draft.title),
    description: draft.description.trim(),
    target: draft.target === SCHOOL_TARGET ? { type: "school" } : { type: "class", class_id: draft.target },
    questions: draft.questions.map((question) => ({
      type: question.type,
      label: collapse(question.label),
      required: question.required,
      options: isChoice(question.type) ? question.options.map(collapse) : [],
    })),
  };
}

export function emptyAnswers(questions: FormQuestion[]): AnswerState {
  const state: AnswerState = {};
  for (const question of questions) {
    state[question.id] = { text: "", options: [] };
  }
  return state;
}

export function answerProblems(questions: FormQuestion[], answers: AnswerState): Record<string, Problem> {
  const problems: Record<string, Problem> = {};
  for (const question of questions) {
    const entry = answers[question.id] ?? { text: "", options: [] };
    if (isChoice(question.type)) {
      if (question.required && entry.options.length === 0) {
        problems[question.id] = { code: "form_answer_required" };
      }
      continue;
    }
    const text = entry.text.trim();
    const limit = question.type === "short_text" ? FORM_LIMITS.shortText : FORM_LIMITS.longText;
    if (question.required && text === "") {
      problems[question.id] = { code: "form_answer_required" };
    } else if (text.length > limit) {
      problems[question.id] = { code: "form_answer_too_long", params: { max: limit } };
    }
  }
  return problems;
}

export function buildAnswers(questions: FormQuestion[], answers: AnswerState): FormAnswerPayload[] {
  const payload: FormAnswerPayload[] = [];
  for (const question of questions) {
    const entry = answers[question.id];
    if (!entry) {
      continue;
    }
    if (isChoice(question.type)) {
      if (entry.options.length > 0) {
        payload.push({ question_id: question.id, options: entry.options });
      }
    } else if (entry.text.trim() !== "") {
      payload.push({ question_id: question.id, text: entry.text.trim() });
    }
  }
  return payload;
}

export function answerText(value: FormAnswerValue | null | undefined): string | null {
  return value && "text" in value ? value.text : null;
}

export function percentage(count: number, total: number): number {
  return total > 0 ? Math.round((count / total) * 100) : 0;
}
