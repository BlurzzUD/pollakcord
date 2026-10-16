import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { Attachment, MediaConfig } from "../../api/types";

export function useComposerMedia(target: { scope: "dm" | "channel"; id: string }, config: MediaConfig | undefined) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [giphyId, setGiphyId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<{ filename: string; percent: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const pending = useRef(new Set<string>());
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    setAttachments([]);
    setGiphyId(null);
    setUploading(false);
    setProgress(null);
    setError(null);
    return () => {
      generation.current += 1;
      controller.current?.abort();
      controller.current = null;
      for (const id of pending.current) {
        void api.del(`/uploads/attachments/${id}`).catch(() => undefined);
      }
      pending.current.clear();
    };
  }, [target.scope, target.id]);

  const selectFiles = async (files: File[]) => {
    if (!config || controller.current || files.length === 0) {
      return;
    }
    setError(null);
    if (pending.current.size + files.length > config.max_attachments) {
      setError(new ApiError(422, "attachment_limit_reached", "attachment_limit_reached", { max: config.max_attachments }));
      return;
    }
    if (files.some((file) => file.size > config.max_attachment_bytes)) {
      setError(new ApiError(413, "file_too_large", "file_too_large", { max_bytes: config.max_attachment_bytes }));
      return;
    }
    const current = generation.current;
    const next = new AbortController();
    controller.current = next;
    setUploading(true);
    try {
      for (const file of files) {
        setProgress({ filename: file.name, percent: 0 });
        const uploaded = await api.upload<Attachment>("/uploads/attachments", file, {
          query: { scope: target.scope, scope_id: target.id }, signal: next.signal,
          onProgress: (percent) => current === generation.current && setProgress({ filename: file.name, percent }),
        });
        if (current !== generation.current) {
          void api.del(`/uploads/attachments/${uploaded.id}`).catch(() => undefined);
          return;
        }
        pending.current.add(uploaded.id);
        setAttachments((items) => [...items, uploaded]);
      }
    } catch (failure) {
      if (current === generation.current && !next.signal.aborted) {
        setError(failure);
      }
    } finally {
      if (current === generation.current) {
        controller.current = null;
        setUploading(false);
        setProgress(null);
      }
    }
  };

  const remove = (id: string) => {
    pending.current.delete(id);
    setAttachments((items) => items.filter((item) => item.id !== id));
    void api.del(`/uploads/attachments/${id}`).catch(() => undefined);
  };

  const commit = () => {
    pending.current.clear();
    setAttachments([]);
    setGiphyId(null);
  };

  return { attachments, giphyId, setGiphyId, uploading, progress, error, selectFiles, remove, commit };
}
