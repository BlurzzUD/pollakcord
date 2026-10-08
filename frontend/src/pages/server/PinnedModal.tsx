import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { Message } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Modal } from "../../components/Modal";
import { formatDateTime } from "../../utils/format";

export function PinnedModal({ channelId, onClose }: { channelId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const pins = useQuery({ queryKey: ["pins", channelId], queryFn: () => api.get<Message[]>(`/channels/${channelId}/pins`) });
  return (
    <Modal title={t("channel.pinned")} onClose={onClose}>
      {(pins.data ?? []).length === 0 ? (
        <EmptyState icon="pin" title={t("channel.no_pins")} />
      ) : (
        <ul className="list">
          {(pins.data ?? []).map((message) => (
            <li key={message.id} className="pin">
              <strong>{message.author?.display_name}</strong> <time className="muted">{formatDateTime(message.created_at)}</time>
              <p>{message.content}</p>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
