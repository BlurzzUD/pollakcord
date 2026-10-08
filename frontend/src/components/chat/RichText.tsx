import { useTranslation } from "react-i18next";

import { useUi } from "../../store/ui";
import { isSafeUrl, tokenizeMessage } from "../../utils/text";

export function RichText({ content, names }: { content: string; names: Record<string, string> }) {
  const { t } = useTranslation();
  const openProfile = useUi((state) => state.openProfile);
  return (
    <>
      {tokenizeMessage(content).map((part, index) => {
        if (part.type === "mention") {
          const name = names[part.userId];
          return (
            <button key={index} type="button" className="mention" onClick={() => openProfile(part.userId)}>
              @{name ?? t("message.unknown_user")}
            </button>
          );
        }
        if (part.type === "link" && isSafeUrl(part.value)) {
          return (
            <a key={index} href={part.value} target="_blank" rel="noopener noreferrer nofollow ugc">
              {part.value}
            </a>
          );
        }
        return <span key={index}>{part.type === "text" ? part.value : part.type === "link" ? part.value : ""}</span>;
      })}
    </>
  );
}
