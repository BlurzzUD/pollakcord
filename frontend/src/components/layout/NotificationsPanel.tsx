import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { useNotifications } from "../../api/hooks";
import { formatRelative } from "../../utils/format";
import { describeNotification } from "../../utils/notifications";
import { EmptyState } from "../EmptyState";
import { DokDismiss } from "../dok/DokDismiss";
import { Modal } from "../Modal";

export function NotificationsPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const notifications = useNotifications();
  const readAll = useMutation({
    mutationFn: () => api.post("/notifications/read", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => api.post("/notifications/read", { ids: [id] }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const items = notifications.data?.items ?? [];
  return (
    <Modal
      title={t("notifications.title")}
      onClose={onClose}
      footer={
        <button type="button" className="button button--ghost" onClick={() => readAll.mutate()} disabled={!notifications.data?.unread}>
          {t("notifications.mark_all_read")}
        </button>
      }
    >
      {items.length === 0 ? (
        <EmptyState icon="bell" title={t("notifications.empty")} />
      ) : (
        <ul className="list">
          {items.map((item) => {
            const described = describeNotification(t, item);
            const dismissable = item.type === "dok_message" && !item.read;
            return (
              <li key={item.id} className={dismissable ? "list__row list__row--grow" : undefined}>
                <button
                  type="button"
                  className={`list__item${item.read ? "" : " is-unread"}`}
                  onClick={() => {
                    void api.post("/notifications/read", { ids: [item.id] }).then(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }));
                    if (described.href) {
                      onClose();
                      navigate(described.href);
                    }
                  }}
                >
                  <span>{described.text}</span>
                  <time className="muted" dateTime={item.created_at}>
                    {formatRelative(item.created_at)}
                  </time>
                </button>
                {dismissable ? <DokDismiss onDismiss={() => dismiss.mutate(item.id)} busy={dismiss.isPending} /> : null}
              </li>
            );
          })}
        </ul>
      )}
    </Modal>
  );
}
