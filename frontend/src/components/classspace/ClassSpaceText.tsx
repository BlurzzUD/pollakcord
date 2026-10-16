import { isSafeUrl, tokenizeMessage } from "../../utils/text";
import { SafeLink } from "../SafeLink";

export function ClassSpaceText({ content }: { content: string }) {
  return (
    <>
      {tokenizeMessage(content).map((part, index) => {
        if (part.type === "link" && isSafeUrl(part.value)) {
          return (
            <SafeLink key={index} href={part.value}>
              {part.value}
            </SafeLink>
          );
        }
        return <span key={index}>{part.type === "mention" ? `<@${part.userId}>` : part.value}</span>;
      })}
    </>
  );
}
