import { useTranslation } from "react-i18next";

import { useClassSpaceMembers } from "../../api/hooks";
import { Avatar } from "../Avatar";
import { Spinner } from "../EmptyState";
import { ErrorText } from "../ErrorText";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

interface ClassSpaceMembersDialogProps {
  classId: string;
  code: string;
  onClose: () => void;
}

export function ClassSpaceMembersDialog({ classId, code, onClose }: ClassSpaceMembersDialogProps) {
  const { t } = useTranslation();
  const members = useClassSpaceMembers(classId);
  const data = members.data;
  return (
    <Modal
      title={t("classSpace.members_title", { code })}
      onClose={onClose}
      footer={
        <button type="button" className="button button--ghost" onClick={onClose}>
          {t("common.close")}
        </button>
      }
    >
      {members.isPending ? <Spinner label={t("common.loading")} /> : null}
      <ErrorText error={members.error} />
      {data ? (
        <>
          <ul className="class-space-members">
            {data.members.map((entry) => (
              <li key={entry.user.id}>
                <div className="member">
                  <Avatar name={entry.user.display_name} url={entry.user.avatar_url} size={32} />
                  <span className="member__name">
                    {entry.user.display_name} <span className="muted">@{entry.user.username}</span>
                  </span>
                  {entry.mine ? <span className="badge">{t("classSpace.you")}</span> : null}
                </div>
                {entry.mine && !entry.show_username ? <p className="muted class-space-members__own">{t("classSpace.members_mine_hidden")}</p> : null}
              </li>
            ))}
          </ul>
          {data.hidden_count > 0 ? (
            <p className="class-space-members__hidden">
              <Icon name="lock" size={16} /> {t("classSpace.members_hidden", { count: data.hidden_count })}
            </p>
          ) : null}
        </>
      ) : null}
    </Modal>
  );
}
