import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import type { ServerDetail } from "../../api/types";
import { ErrorText } from "../ErrorText";
import { TextAreaField, TextField } from "../Field";
import { Modal } from "../Modal";

function extractCode(value: string): string {
  const trimmed = value.trim();
  const match = /\/invite\/([A-Za-z0-9]+)/.exec(trimmed);
  return match ? match[1] : trimmed;
}

export function CreateJoinServer({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"create" | "join">("create");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState("");

  const create = useMutation({
    mutationFn: () => api.post<ServerDetail>("/servers", { name, description }),
    onSuccess: async (server) => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      onClose();
      const first = server.channels.find((channel) => channel.type === "text");
      navigate(`/app/server/${server.id}${first ? `/${first.id}` : ""}`);
    },
  });
  const join = useMutation({
    mutationFn: () => api.post<{ server_id: string }>(`/invites/${extractCode(code)}/accept`),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      onClose();
      navigate(`/app/server/${result.server_id}`);
    },
  });

  return (
    <Modal title={t("server.add_title")} onClose={onClose}>
      <div className="tabs" role="tablist">
        {(["create", "join"] as const).map((value) => (
          <button key={value} type="button" role="tab" aria-selected={tab === value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}>
            {t(`server.tab_${value}`)}
          </button>
        ))}
      </div>
      {tab === "create" ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <TextField label={t("server.name")} value={name} onChange={(event) => setName(event.target.value)} maxLength={60} required data-autofocus />
          <TextAreaField label={t("server.description")} value={description} onChange={(event) => setDescription(event.target.value)} maxLength={500} rows={3} />
          <ErrorText error={create.error} />
          <button type="submit" className="button button--primary" disabled={create.isPending || !name.trim()}>
            {t("server.create")}
          </button>
        </form>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            join.mutate();
          }}
        >
          <TextField label={t("server.invite_code_or_link")} hint={t("server.invite_hint")} value={code} onChange={(event) => setCode(event.target.value)} required data-autofocus autoComplete="off" />
          <ErrorText error={join.error} />
          <button type="submit" className="button button--primary" disabled={join.isPending || !code.trim()}>
            {t("server.join")}
          </button>
        </form>
      )}
    </Modal>
  );
}
