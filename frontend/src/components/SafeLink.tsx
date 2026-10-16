import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isExternalUrl, useLinkPolicy } from "../utils/links";
import { isSafeUrl } from "../utils/text";
import { Modal } from "./Modal";

export function SafeLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  const { t } = useTranslation();
  const publicOrigin = useLinkPolicy((state) => state.publicOrigin);
  const [pending, setPending] = useState(false);
  if (!isSafeUrl(href)) {
    return <span>{children}</span>;
  }
  const external = isExternalUrl(href, publicOrigin ?? window.location.origin);
  const activate = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (external) {
      event.preventDefault();
      event.stopPropagation();
      setPending(true);
    }
  };
  return (
    <>
      <a href={href} className={className} target="_blank" rel="noopener noreferrer nofollow ugc" onClick={activate} onAuxClick={(event) => event.button === 1 && activate(event)} onContextMenu={(event) => external && activate(event)} draggable={false}>
        {children}
      </a>
      {pending ? (
        <Modal
          title={t("media.external_title")}
          onClose={() => setPending(false)}
          footer={
            <>
              <button type="button" className="button" data-autofocus onClick={() => setPending(false)}>{t("common.cancel")}</button>
              <a className="button button--primary" href={href} target="_blank" rel="noopener noreferrer" onClick={() => setPending(false)}>{t("media.continue")}</a>
            </>
          }
        >
          <p>{t("media.external_warning")}</p>
          <p className="external-link-url" dir="auto">{href}</p>
        </Modal>
      ) : null}
    </>
  );
}
