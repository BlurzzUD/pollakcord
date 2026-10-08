import { hueFor, initials } from "../utils/text";

interface AvatarProps {
  name: string;
  url?: string | null;
  size?: number;
  presence?: "online" | "offline" | null;
  rounded?: boolean;
}

export function Avatar({ name, url, size = 40, presence, rounded = true }: AvatarProps) {
  const style = { width: size, height: size, fontSize: size * 0.4 };
  return (
    <span className={`avatar${rounded ? "" : " avatar--square"}`} style={style} data-presence={presence ?? undefined}>
      {url ? (
        <img src={url} alt="" width={size} height={size} loading="lazy" decoding="async" />
      ) : (
        <span className="avatar__fallback" style={{ background: `hsl(${hueFor(name)} 55% 42%)` }} aria-hidden="true">
          {initials(name)}
        </span>
      )}
      {presence ? <span className={`avatar__dot avatar__dot--${presence}`} aria-hidden="true" /> : null}
    </span>
  );
}
