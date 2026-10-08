import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../../api/client";
import type { Me, SavedTheme, ThemeMode, ThemeTokens } from "../../api/types";
import { ErrorText } from "../../components/ErrorText";
import { SelectField, TextAreaField, TextField, Toggle } from "../../components/Field";
import { LANGUAGES, isLanguage } from "../../i18n";
import { useAuth } from "../../store/auth";
import { COLOR_KEYS, DEFAULT_CUSTOM, GRADIENT, PRESETS, contrastRatio } from "../../theme/tokens";
import { useSaveSettings } from "./useSaveSettings";

function CssError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!(error instanceof ApiError)) {
    return <ErrorText error={error} />;
  }
  if (error.code === "css_rejected") {
    const reason = String(error.params.reason ?? "");
    return (
      <p className="form-error" role="alert">
        {t("errors.css_rejected", { reason: t(`errors.${reason}`, { defaultValue: reason }) })}
      </p>
    );
  }
  return <ErrorText error={error} />;
}

function ThemeEditor({ themes, me }: { themes: SavedTheme[]; me: Me }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const setMe = useAuth((state) => state.setMe);
  const active = themes.find((theme) => theme.id === me.settings.active_theme_id);
  const [editingId, setEditingId] = useState<string | null>(active?.id ?? null);
  const [name, setName] = useState(active?.name ?? t("appearance.my_theme"));
  const [tokens, setTokens] = useState<ThemeTokens>({ ...DEFAULT_CUSTOM, ...(active?.tokens ?? {}) });
  const [gradient, setGradient] = useState(Boolean(tokens.background && GRADIENT.test(tokens.background)));
  const [angle, setAngle] = useState(160);
  const [from, setFrom] = useState(tokens.bg ?? "#fafbff");
  const [to, setTo] = useState(tokens.bg_alt ?? "#e5eaf8");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["themes"] });
  const payload = () => ({ name, tokens: { ...tokens, ...(gradient ? { background: `linear-gradient(${angle}deg, ${from}, ${to})` } : { background: undefined }) } });
  const create = useMutation({
    mutationFn: () => api.post<SavedTheme>("/me/themes", payload()),
    onSuccess: async (theme) => {
      setEditingId(theme.id);
      await refresh();
    },
  });
  const update = useMutation({ mutationFn: () => api.put<SavedTheme>(`/me/themes/${editingId}`, payload()), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/me/themes/${id}`),
    onSuccess: async () => {
      setEditingId(null);
      await refresh();
    },
  });
  const activate = useMutation({
    mutationFn: (id: string) => api.patch<Me>("/me/settings", { theme_mode: "custom", active_theme_id: id }),
    onSuccess: (updated) => setMe(updated),
  });
  const load = (theme: SavedTheme) => {
    setEditingId(theme.id);
    setName(theme.name);
    setTokens({ ...DEFAULT_CUSTOM, ...theme.tokens });
    setGradient(Boolean(theme.tokens.background && GRADIENT.test(theme.tokens.background)));
  };
  const low = contrastRatio(tokens.text ?? "#000000", tokens.bg ?? "#ffffff") < 4.5 || contrastRatio(tokens.accent_text ?? "#ffffff", tokens.accent ?? "#000000") < 4.5;

  return (
    <div className="theme-editor">
      <h3>{t("appearance.custom_theme")}</h3>
      <div className="chips">
        {PRESETS.map((preset) => (
          <button key={preset.id} type="button" className="button button--small button--outline" onClick={() => setTokens({ ...DEFAULT_CUSTOM, ...preset.tokens })}>
            {t(`appearance.preset_${preset.id}`)}
          </button>
        ))}
      </div>
      {themes.length > 0 ? (
        <ul className="list">
          {themes.map((theme) => (
            <li key={theme.id} className="list__row">
              <button type="button" className={`list__item${theme.id === editingId ? " is-active" : ""}`} onClick={() => load(theme)}>
                {theme.name} {theme.id === me.settings.active_theme_id ? <span className="badge">{t("appearance.active")}</span> : null}
              </button>
              <button type="button" className="button button--small" onClick={() => activate.mutate(theme.id)}>
                {t("appearance.use")}
              </button>
              <button type="button" className="button button--small button--danger-ghost" onClick={() => remove.mutate(theme.id)}>
                {t("common.delete")}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <TextField label={t("appearance.theme_name")} value={name} onChange={(event) => setName(event.target.value)} maxLength={40} />
      <div className="color-grid">
        {COLOR_KEYS.map((key) => (
          <label key={key} className="color-input">
            <span>{t(`appearance.token_${key}`)}</span>
            <input type="color" value={tokens[key] ?? DEFAULT_CUSTOM[key]} onChange={(event) => setTokens({ ...tokens, [key]: event.target.value })} />
          </label>
        ))}
      </div>
      <Toggle label={t("appearance.gradient_background")} checked={gradient} onChange={setGradient} />
      {gradient ? (
        <div className="inline-form">
          <TextField label={t("appearance.gradient_angle")} type="number" min={0} max={360} value={angle} onChange={(event) => setAngle(Number(event.target.value))} />
          <label className="color-input">
            <span>{t("appearance.gradient_from")}</span>
            <input type="color" value={from} onChange={(event) => setFrom(event.target.value)} />
          </label>
          <label className="color-input">
            <span>{t("appearance.gradient_to")}</span>
            <input type="color" value={to} onChange={(event) => setTo(event.target.value)} />
          </label>
        </div>
      ) : null}
      <TextField label={t("appearance.radius")} type="range" min={0} max={24} value={tokens.radius ?? "10"} onChange={(event) => setTokens({ ...tokens, radius: event.target.value })} />
      {low ? <p className="form-error" role="status">{t("appearance.low_contrast")}</p> : null}
      <div className="theme-preview" style={{ background: tokens.bg, color: tokens.text, borderColor: tokens.border, borderRadius: `${tokens.radius ?? 10}px` }}>
        <strong style={{ color: tokens.accent }}>PollákCord</strong>
        <p>{t("appearance.preview_text")}</p>
        <p style={{ color: tokens.text_muted }}>{t("appearance.preview_muted")}</p>
        <span style={{ background: tokens.mention, color: tokens.text, padding: "0 .3rem", borderRadius: 4 }}>@mention</span>{" "}
        <span style={{ background: tokens.accent, color: tokens.accent_text, padding: ".2rem .6rem", borderRadius: 6 }}>{t("appearance.preview_button")}</span>
      </div>
      <ErrorText error={create.error ?? update.error ?? remove.error ?? activate.error} />
      <div className="button-row">
        <button type="button" className="button button--primary" onClick={() => (editingId ? update.mutate() : create.mutate())} disabled={create.isPending || update.isPending}>
          {editingId ? t("common.save") : t("appearance.save_new")}
        </button>
        {editingId ? (
          <button type="button" className="button button--outline" onClick={() => create.mutate()}>
            {t("appearance.save_as_new")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function AppearanceSection() {
  const { t } = useTranslation();
  const me = useAuth((state) => state.me) as Me;
  const setMe = useAuth((state) => state.setMe);
  const save = useSaveSettings();
  const themes = useQuery({ queryKey: ["themes"], queryFn: () => api.get<SavedTheme[]>("/me/themes") });
  const [css, setCss] = useState(me.settings.custom_css);
  const [density, setDensity] = useState(me.settings.chat_appearance);
  const saveCss = useMutation({ mutationFn: () => api.patch<Me>("/me/settings", { custom_css: css }), onSuccess: (updated) => setMe(updated) });
  const modes: ThemeMode[] = ["system", "dark", "light", "custom"];

  return (
    <div className="section">
      <h2>{t("settings.appearance")}</h2>
      <SelectField
        label={t("settings.language")}
        value={me.settings.language}
        onChange={(event) => isLanguage(event.target.value) && save.mutate({ language: event.target.value })}
        options={LANGUAGES.map((language) => ({ value: language.code, label: language.label }))}
      />
      <fieldset className="radio-group">
        <legend>{t("appearance.theme")}</legend>
        {modes.map((mode) => (
          <label key={mode} className="check">
            <input type="radio" name="theme-mode" checked={me.settings.theme_mode === mode} onChange={() => save.mutate({ theme_mode: mode })} />
            <span>{t(`appearance.mode_${mode}`)}</span>
          </label>
        ))}
      </fieldset>
      {me.settings.theme_mode === "custom" || (themes.data ?? []).length > 0 ? <ThemeEditor themes={themes.data ?? []} me={me} /> : (
        <button type="button" className="button button--outline" onClick={() => save.mutate({ theme_mode: "custom" })}>
          {t("appearance.start_custom")}
        </button>
      )}
      <h3>{t("appearance.chat")}</h3>
      <fieldset className="radio-group">
        <legend>{t("appearance.density")}</legend>
        {(["cozy", "compact"] as const).map((value) => (
          <label key={value} className="check">
            <input type="radio" name="density" checked={density.density === value} onChange={() => { const next = { ...density, density: value }; setDensity(next); save.mutate({ chat_appearance: next }); }} />
            <span>{t(`appearance.density_${value}`)}</span>
          </label>
        ))}
      </fieldset>
      <TextField
        label={t("appearance.font_scale", { value: density.font_scale })}
        type="range"
        min={80}
        max={140}
        step={5}
        value={density.font_scale}
        onChange={(event) => setDensity({ ...density, font_scale: Number(event.target.value) })}
        onMouseUp={() => save.mutate({ chat_appearance: density })}
        onKeyUp={() => save.mutate({ chat_appearance: density })}
        onTouchEnd={() => save.mutate({ chat_appearance: density })}
      />
      <Toggle label={t("appearance.show_timestamps")} checked={density.show_timestamps} onChange={(value) => { const next = { ...density, show_timestamps: value }; setDensity(next); save.mutate({ chat_appearance: next }); }} />
      <h3>{t("appearance.custom_css")}</h3>
      <div className="notice" role="note">
        <strong>{t("appearance.css_safety_title")}</strong>
        <p>{t("appearance.css_safety_text")}</p>
      </div>
      <TextAreaField label={t("appearance.custom_css")} hint={t("appearance.css_hint")} value={css} onChange={(event) => setCss(event.target.value)} rows={10} spellCheck={false} className="code-area" maxLength={32768} />
      <CssError error={saveCss.error} />
      <div className="button-row">
        <button type="button" className="button button--primary" onClick={() => saveCss.mutate()} disabled={saveCss.isPending}>
          {t("appearance.apply_css")}
        </button>
        <button
          type="button"
          className="button button--ghost"
          onClick={() => {
            setCss("");
            saveCss.reset();
            save.mutate({ custom_css: "" });
          }}
        >
          {t("appearance.clear_css")}
        </button>
      </div>
    </div>
  );
}
