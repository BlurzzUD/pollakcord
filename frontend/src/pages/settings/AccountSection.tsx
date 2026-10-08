import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { Me, SchoolClass } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { CopyId } from "../../components/CopyId";
import { ErrorText } from "../../components/ErrorText";
import { SelectField, TextAreaField, TextField } from "../../components/Field";
import { useAuth } from "../../store/auth";
import { useUi } from "../../store/ui";

function ImageControl({ kind, me }: { kind: "avatar" | "banner"; me: Me }) {
  const { t } = useTranslation();
  const setMe = useAuth((state) => state.setMe);
  const input = useRef<HTMLInputElement>(null);
  const url = kind === "avatar" ? me.avatar_url : me.banner_url;
  const upload = useMutation({ mutationFn: (file: File) => api.upload<Me>(`/uploads/${kind}`, file), onSuccess: setMe });
  const remove = useMutation({ mutationFn: () => api.del<Me>(`/uploads/${kind}`), onSuccess: setMe });
  return (
    <div className="image-control">
      {kind === "avatar" ? <Avatar name={me.display_name} url={url} size={84} /> : <div className="image-control__banner" style={url ? { backgroundImage: `url(${url})` } : undefined} role="img" aria-label={t("settings.banner")} />}
      <div>
        <strong>{t(`settings.${kind}`)}</strong>
        <p className="muted">{t("settings.image_rules")}</p>
        <div className="button-row">
          <input ref={input} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(event) => event.target.files?.[0] && upload.mutate(event.target.files[0])} />
          <button type="button" className="button button--outline" onClick={() => input.current?.click()} disabled={upload.isPending}>
            {t("settings.upload_image")}
          </button>
          {url ? (
            <button type="button" className="button button--ghost" onClick={() => remove.mutate()}>
              {t("settings.remove_image")}
            </button>
          ) : null}
        </div>
        <ErrorText error={upload.error ?? remove.error} />
      </div>
    </div>
  );
}

export function AccountSection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me) as Me;
  const setMe = useAuth((state) => state.setMe);
  const push = useUi((state) => state.push);
  const [displayName, setDisplayName] = useState(me.display_name);
  const [bio, setBio] = useState(me.bio);
  const [accent, setAccent] = useState(me.accent_color ?? "#2540d9");
  const [useAccent, setUseAccent] = useState(Boolean(me.accent_color));
  const [classId, setClassId] = useState("");
  const [visibility, setVisibility] = useState(me.settings.privacy.class_visibility);
  const classes = useQuery({ queryKey: ["classes"], queryFn: () => api.get<SchoolClass[]>("/me/classes") });
  const currentClass = classes.data?.find((item) => item.code === me.class_code);

  const save = useMutation({
    mutationFn: () => api.patch<Me>("/me", { display_name: displayName, bio, ...(useAccent ? { accent_color: accent } : { clear_accent: true }) }),
    onSuccess: (updated) => {
      setMe(updated);
      push("success", t("common.saved"));
    },
  });
  const saveClass = useMutation({
    mutationFn: () => api.put<Me>("/me/class", { class_id: classId || currentClass?.id, visibility }),
    onSuccess: (updated) => {
      setMe(updated);
      push("success", t("common.saved"));
    },
  });

  return (
    <div className="section">
      <h2>{t("settings.account")}</h2>
      <p className="notice">{t("settings.real_name_note")}</p>
      <ImageControl kind="avatar" me={me} />
      <ImageControl kind="banner" me={me} />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <TextField label={t("auth.username")} value={me.username} readOnly hint={t("settings.username_fixed")} />
        <TextField label={t("auth.display_name")} value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={32} required />
        <TextAreaField label={t("settings.bio")} value={bio} onChange={(event) => setBio(event.target.value)} maxLength={300} rows={3} />
        <div className="inline-form">
          <label className="check">
            <input type="checkbox" checked={useAccent} onChange={(event) => setUseAccent(event.target.checked)} />
            <span>{t("settings.accent_color")}</span>
          </label>
          {useAccent ? <input type="color" aria-label={t("settings.accent_color")} value={accent} onChange={(event) => setAccent(event.target.value)} /> : null}
        </div>
        <CopyId value={me.id} label={t("developer.user_id")} />
        <ErrorText error={save.error} />
        <button type="submit" className="button button--primary" disabled={save.isPending}>
          {t("common.save")}
        </button>
      </form>
      <h3>{t("class.settings_title")}</h3>
      <p className="muted">{t("class.settings_text")}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          saveClass.mutate();
        }}
      >
        <SelectField
          label={t("class.choose")}
          value={classId || currentClass?.id || ""}
          onChange={(event) => setClassId(event.target.value)}
          options={[{ value: "", label: t("class.select_placeholder") }, ...(classes.data ?? []).map((item) => ({ value: item.id, label: item.code }))]}
        />
        <SelectField
          label={t("class.who_sees")}
          value={visibility}
          onChange={(event) => setVisibility(event.target.value as typeof visibility)}
          options={(["hidden", "friends", "shared_servers", "everyone"] as const).map((value) => ({ value, label: t(`privacy.class_visibility_${value}`) }))}
        />
        <ErrorText error={saveClass.error} />
        <button type="submit" className="button button--primary" disabled={saveClass.isPending || (visibility !== "hidden" && !(classId || currentClass))}>
          {t("common.save")}
        </button>
      </form>
    </div>
  );
}
