import { Link } from "react-router-dom";

export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="14" fill="var(--ink)" />
      <path d="M14 20h36M14 32h36M14 44h36M26 12v40M38 12v40" stroke="var(--ink-text)" strokeOpacity=".28" strokeWidth="2" />
      <path d="M20 46V18h13a9 9 0 0 1 0 18H20" fill="none" stroke="var(--ink-text)" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 10v44" stroke="var(--margin)" strokeWidth="3" />
    </svg>
  );
}

export function Brand({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="brand">
      <Logo />
      <span className="brand__name">PollákCord</span>
    </Link>
  );
}
