import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useUi } from "../store/ui";
import { Icon } from "./Icon";

export function PageHeader({ title, lead, children }: { title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  const { t } = useTranslation();
  const setDrawer = useUi((state) => state.setDrawer);
  return (
    <header className="page-header">
      <button type="button" className="icon-button page-header__menu" onClick={() => setDrawer(true)} aria-label={t("a11y.open_menu")}>
        <Icon name="menu" />
      </button>
      {lead}
      <h1>{title}</h1>
      <div className="page-header__actions">{children}</div>
    </header>
  );
}
