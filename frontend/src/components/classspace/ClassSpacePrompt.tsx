import { useTranslation } from "react-i18next";

import { useClassSpace } from "../../api/hooks";
import { useClassSpaceUi } from "../../store/classSpace";
import { ErrorText } from "../ErrorText";
import { Modal } from "../Modal";
import { useAnswerClassSpace } from "./useAnswerClassSpace";

export function ClassSpacePrompt() {
  const { t } = useTranslation();
  const space = useClassSpace();
  const dismissedFor = useClassSpaceUi((state) => state.dismissedFor);
  const dismiss = useClassSpaceUi((state) => state.dismiss);
  const answer = useAnswerClassSpace();
  const state = space.data;
  if (!state || !state.class || !state.prompt_required || dismissedFor === state.class.id) {
    return null;
  }
  const school = state.class;
  return (
    <Modal title={t("classSpace.page_title", { code: school.code })} onClose={() => dismiss(school.id)}>
      <p>{t("classSpace.prompt_intro", { code: school.code })}</p>
      <p className="class-space-question">{t("classSpace.prompt_question")}</p>
      <ul className="class-space-points">
        <li>{t("classSpace.prompt_yes")}</li>
        <li>{t("classSpace.prompt_no")}</li>
      </ul>
      <p className="muted">{t("classSpace.prompt_note")}</p>
      <ErrorText error={answer.error} />
      <div className="class-space-actions">
        <button type="button" className="button button--ghost class-space-actions__later" onClick={() => dismiss(school.id)} disabled={answer.isPending}>
          {t("classSpace.later")}
        </button>
        <button type="button" className="button button--outline" onClick={() => answer.mutate(false)} disabled={answer.isPending} data-autofocus>
          {t("classSpace.answer_no")}
        </button>
        <button type="button" className="button button--primary" onClick={() => answer.mutate(true)} disabled={answer.isPending}>
          {t("classSpace.answer_yes")}
        </button>
      </div>
    </Modal>
  );
}
