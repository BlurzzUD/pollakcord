import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { FormDetail, FormSummary } from "../../api/types";
import { useUi } from "../../store/ui";
import { ConfirmDialog } from "../ConfirmDialog";
import { errorMessage } from "../ErrorText";

type Manageable = Pick<FormSummary, "id" | "title" | "status" | "can_manage">;

export function FormManageActions({ form, onDeleted }: { form: Manageable; onDeleted?: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const push = useUi((state) => state.push);
  const [confirming, setConfirming] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["forms"] });
  const toggle = useMutation({
    mutationFn: () => api.patch<FormDetail>(`/forms/${form.id}`, { status: form.status === "open" ? "closed" : "open" }),
    onSuccess: (updated) => {
      push("success", updated.status === "closed" ? t("forms.closed_toast") : t("forms.reopened_toast"));
      void refresh();
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/forms/${form.id}`),
    onSuccess: () => {
      setConfirming(false);
      push("success", t("forms.deleted_toast"));
      void refresh();
      onDeleted?.();
    },
    onError: (failure) => {
      setConfirming(false);
      push("error", errorMessage(t, failure));
    },
  });
  if (!form.can_manage) {
    return null;
  }
  return (
    <>
      <button type="button" className="button button--small button--ghost" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
        {form.status === "open" ? t("forms.close_form") : t("forms.reopen_form")}
      </button>
      <button type="button" className="button button--small button--danger-ghost" onClick={() => setConfirming(true)}>
        {t("common.delete")}
      </button>
      {confirming ? (
        <ConfirmDialog
          title={t("forms.delete_title")}
          message={t("forms.delete_message", { title: form.title })}
          confirmLabel={t("common.delete")}
          danger
          busy={remove.isPending}
          onConfirm={() => remove.mutate()}
          onCancel={() => setConfirming(false)}
        />
      ) : null}
    </>
  );
}
