import type { DokRole, DokScope, DokTarget, DokThread } from "../api/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export const DISMISS_DELAY_MS = 3000;
export const SCHOOL_VALUE = "school";

export function roleLabel(t: Translate, role: DokRole): string {
  return role === "dok_president" ? t("dok.role_president") : t("dok.role_representative");
}

export function placeLabel(t: Translate, scope: DokScope, classCode: string | null | undefined): string {
  return scope === "school" ? t("dok.school") : (classCode ?? "");
}

export function targetValue(target: DokTarget): string {
  return target.type === "school" ? SCHOOL_VALUE : `class:${target.class_id}`;
}

export function targetLabel(t: Translate, target: DokTarget): string {
  return target.type === "school" ? t("dok.target_school") : t("dok.target_class", { code: target.code });
}

export function threadLabel(t: Translate, thread: Pick<DokThread, "scope" | "class">): string {
  return thread.scope === "school" ? t("dok.school") : t("dok.class_thread", { code: thread.class?.code ?? "" });
}

export function threadTargetValue(thread: Pick<DokThread, "scope" | "class">): string {
  return thread.scope === "school" || !thread.class ? SCHOOL_VALUE : `class:${thread.class.id}`;
}
