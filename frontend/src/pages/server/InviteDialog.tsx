import { useTranslation } from "react-i18next";

import type { ServerDetail } from "../../api/types";
import { Modal } from "../../components/Modal";
import { InviteManager } from "./InviteManager";

export function InviteDialog({ server, onClose }: { server: ServerDetail; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal title={t("server.invite_people_to", { name: server.name })} onClose={onClose} wide>
      <InviteManager server={server} withFriends />
    </Modal>
  );
}
