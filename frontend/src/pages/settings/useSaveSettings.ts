import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { Me } from "../../api/types";
import { errorMessage } from "../../components/ErrorText";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";

export function useSaveSettings() {
  const { t } = useTranslation();
  const setMe = useAuth((state) => state.setMe);
  const push = useUi((state) => state.push);
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.patch<Me>("/me/settings", patch),
    onSuccess: (me) => {
      setMe(me);
      push("success", t("common.saved"));
    },
    onError: (failure) => push("error", errorMessage(t, failure)),
  });
}
