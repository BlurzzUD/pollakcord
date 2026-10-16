import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { searchGiphy, type GiphyItem } from "../../api/giphy";
import { ErrorText } from "../ErrorText";
import { Modal } from "../Modal";

export function GiphyPicker({ apiKey, onChoose, onClose }: { apiKey: string; onChoose: (id: string) => void; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<GiphyItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim() || busy) {
      return;
    }
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const timeout = window.setTimeout(() => next.abort(), 10000);
    setBusy(true);
    setError(null);
    try {
      setItems(await searchGiphy(apiKey, query, i18n.language, next.signal));
      setSearched(true);
    } catch (failure) {
      setError(failure);
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  };
  return (
    <Modal title={t("media.giphy_title")} onClose={onClose} wide>
      <form className="giphy-search" onSubmit={(event) => void search(event)}>
        <label htmlFor="giphy-search">{t("media.giphy_search")}</label>
        <input id="giphy-search" value={query} maxLength={50} onChange={(event) => setQuery(event.target.value)} data-autofocus />
        <button type="submit" className="button button--primary" disabled={busy || !query.trim()}>{t("media.search")}</button>
      </form>
      <p className="muted">{t("media.giphy_rating")}</p>
      <ErrorText error={error} />
      <div className="giphy-grid" aria-busy={busy}>
        {items.map((gif) => (
          <button type="button" key={gif.id} className="giphy-result" onClick={() => onChoose(gif.id)} aria-label={t("media.giphy_insert", { title: gif.title })}>
            <img src={gif.preview} alt={gif.title} loading="lazy" referrerPolicy="no-referrer" />
            <span>{gif.attribution}</span>
          </button>
        ))}
      </div>
      {searched && !busy && items.length === 0 ? <p role="status">{t("media.giphy_empty")}</p> : null}
      <p className="giphy-attribution">{t("media.giphy_powered")}</p>
    </Modal>
  );
}
