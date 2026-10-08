import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { Meta } from "../../api/types";
import { useUi } from "../../store/ui";
import { ErrorText } from "../ErrorText";
import { SelectField, TextAreaField, Toggle } from "../Field";
import { Modal } from "../Modal";

export function ReportDialog({ base, messageId, allowEscalate, onClose }: { base: string; messageId: string; allowEscalate: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const push = useUi((state) => state.push);
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/meta"), staleTime: Infinity });
  const [reason, setReason] = useState("harassment");
  const [details, setDetails] = useState("");
  const [escalate, setEscalate] = useState(false);
  const submit = useMutation({
    mutationFn: () => api.post(`${base}/messages/${messageId}/report`, { reason, details, escalate }),
    onSuccess: () => {
      push("success", t("report.sent"));
      onClose();
    },
  });
  return (
    <Modal
      title={t("report.title")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button type="button" className="button button--danger" onClick={() => submit.mutate()} disabled={submit.isPending}>
            {t("report.submit")}
          </button>
        </>
      }
    >
      <p className="muted">{t("report.explain")}</p>
      <SelectField
        label={t("report.reason")}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        options={(meta.data?.report_reasons ?? ["harassment", "spam", "other"]).map((value) => ({ value, label: t(`report.reasons.${value}`) }))}
      />
      <TextAreaField label={t("report.details")} value={details} maxLength={500} rows={3} onChange={(event) => setDetails(event.target.value)} />
      {allowEscalate ? <Toggle label={t("report.escalate")} hint={t("report.escalate_hint")} checked={escalate} onChange={setEscalate} /> : null}
      <ErrorText error={submit.error} />
    </Modal>
  );
}
