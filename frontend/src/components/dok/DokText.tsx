import { isSafeUrl, tokenizeMessage } from "../../utils/text";

export function DokText({ content }: { content: string }) {
  return (
    <>
      {tokenizeMessage(content).map((part, index) => {
        if (part.type === "link" && isSafeUrl(part.value)) {
          return (
            <a key={index} href={part.value} target="_blank" rel="noopener noreferrer nofollow ugc">
              {part.value}
            </a>
          );
        }
        return <span key={index}>{part.type === "mention" ? `<@${part.userId}>` : part.value}</span>;
      })}
    </>
  );
}
