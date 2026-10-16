import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useMediaConfig } from "../../api/hooks";
import { loadGiphy, type GiphyItem } from "../../api/giphy";
import type { Attachment, LinkEmbed } from "../../api/types";
import { SafeLink } from "../SafeLink";

export function formatFileSize(size: number): string {
  return size >= 1_000_000 ? `${(size / 1_000_000).toFixed(1)} MB` : size >= 1000 ? `${(size / 1000).toFixed(1)} kB` : `${size} B`;
}

function previewImage(value: string | null | undefined): string | undefined {
  return value && /^data:image\/webp;base64,[A-Za-z0-9+/=]+$/.test(value) ? value : undefined;
}

export function LinkEmbeds({ embeds = [] }: { embeds?: LinkEmbed[] }) {
  return (
    <div className="link-embeds">
      {embeds.map((embed, index) => (
        <SafeLink key={`${index}:${embed.url}`} href={embed.url} className="link-embed">
          <span className="link-embed__body">
            <span className="link-embed__host">{previewImage(embed.icon) ? <img src={previewImage(embed.icon)} alt="" width={20} height={20} /> : null}{embed.site_name || embed.host}</span>
            <strong>{embed.title || embed.host}</strong>
            {embed.description ? <span className="link-embed__description">{embed.description}</span> : null}
            {embed.site_name ? <span className="muted">{embed.host}</span> : null}
          </span>
          {previewImage(embed.image) ? <img className="link-embed__image" src={previewImage(embed.image)} alt="" loading="lazy" /> : null}
        </SafeLink>
      ))}
    </div>
  );
}

function GiphyGif({ id }: { id: string }) {
  const { t } = useTranslation();
  const config = useMediaConfig();
  const key = config.data?.giphy_api_key;
  const [gif, setGif] = useState<GiphyItem | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setGif(null);
    setFailed(false);
    if (!key) {
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    void loadGiphy(key, id, controller.signal).then((result) => {
      if (!controller.signal.aborted) {
        setGif(result);
        setFailed(!result);
      }
    }).catch(() => setFailed(true));
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [key, id]);
  if (!gif || failed) {
    return <p className="muted">{failed || !key ? t("media.giphy_unavailable") : t("common.loading")}</p>;
  }
  return (
    <figure className="message-gif">
      <SafeLink href={gif.url}><img src={gif.image} alt={gif.title} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} /></SafeLink>
      <figcaption>{t("media.giphy_powered")} · {gif.attribution}</figcaption>
    </figure>
  );
}

export function MessageMedia({ attachments = [], embeds, giphyId }: { attachments?: Attachment[]; embeds?: LinkEmbed[]; giphyId?: string | null }) {
  const { t } = useTranslation();
  return (
    <>
      {attachments.map((file) => {
        if (!/^\/api\/v1\/uploads\/attachments\/\d+$/.test(file.url)) {
          return null;
        }
        return (
          <div key={file.id} className="message-attachment">
            {file.kind === "image" ? <a href={file.url} target="_blank" rel="noopener noreferrer"><img src={`${file.url}?inline=true`} alt={file.filename} loading="lazy" /></a> : null}
            {file.kind === "video" ? <video src={`${file.url}?inline=true`} controls preload="metadata" aria-label={file.filename} /> : null}
            <a className="message-attachment__download" href={file.url} download={file.filename}>
              <strong>{file.filename}</strong>
              <span>{formatFileSize(file.size_bytes)} · {file.mime_type} · {t("media.download")}</span>
            </a>
          </div>
        );
      })}
      {giphyId ? <GiphyGif id={giphyId} /> : null}
      <LinkEmbeds embeds={embeds} />
    </>
  );
}
