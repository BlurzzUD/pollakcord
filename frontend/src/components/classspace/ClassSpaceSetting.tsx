import { useTranslation } from "react-i18next";

import { useClassSpace } from "../../api/hooks";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";
import { ErrorText } from "../ErrorText";
import { SelectField } from "../Field";
import { useAnswerClassSpace } from "./useAnswerClassSpace";

export function ClassSpaceSetting() {
  const { t } = useTranslation();
  const classCode = useAuth((state) => state.me?.class_code);
  const push = useUi((state) => state.push);
  const space = useClassSpace();
  const answer = useAnswerClassSpace();
  const state = space.data;

  if (!classCode) {
    return <p className="muted">{t("classSpace.setting_no_class")}</p>;
  }
  if (!state || !state.class) {
    return null;
  }
  const value = state.show_username === null ? "" : state.show_username ? "show" : "hide";
  const options = [
    ...(value === "" ? [{ value: "", label: t("classSpace.setting_unanswered") }] : []),
    { value: "show", label: t("classSpace.setting_show") },
    { value: "hide", label: t("classSpace.setting_hide") },
  ];
  return (
    <>
      <h3>{t("classSpace.setting_title")}</h3>
      <SelectField
        label={t("classSpace.setting_label")}
        hint={t("classSpace.setting_hint")}
        value={value}
        disabled={answer.isPending}
        options={options}
        onChange={(event) => {
          if (event.target.value === "") {
            return;
          }
          answer.mutate(event.target.value === "show", { onSuccess: () => push("success", t("common.saved")) });
        }}
      />
      <ErrorText error={answer.error} />
    </>
  );
}
