import type { ClassSpaceMessage } from "../api/types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function anonymousLabel(t: Translate, alias: string | null | undefined): string {
  return alias ? t("classSpace.anonymous_alias", { alias }) : t("classSpace.anonymous");
}

export function messageAuthorLabel(t: Translate, message: Pick<ClassSpaceMessage, "author" | "alias" | "mine">): string {
  if (message.mine) {
    return t("classSpace.you");
  }
  return message.author ? message.author.display_name : anonymousLabel(t, message.alias);
}
