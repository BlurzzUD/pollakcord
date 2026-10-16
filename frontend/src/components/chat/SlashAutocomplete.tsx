import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, request } from "../../api/client";
import type { BotCommand } from "../../api/types";
import { BotBadge } from "../BotBadge";
import { ErrorText } from "../ErrorText";
import { SelectField, TextField } from "../Field";
import { Modal } from "../Modal";

export interface SlashHandle {
  keyDown: (key: string) => boolean;
  openFirst: () => void;
}

export const SlashAutocomplete = forwardRef<SlashHandle, { channelId: string; text: string; onComplete: () => void }>(function SlashAutocomplete({ channelId, text, onComplete }, ref) {
  const { t } = useTranslation();
  const [commands, setCommands] = useState<BotCommand[]>([]);
  const [selected, setSelected] = useState<BotCommand | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const query = text.slice(1).trim().toLowerCase();
  const suggestions = commands.filter((command) => command.name.startsWith(query)).slice(0, 8);
  useEffect(() => {
    const abort = new AbortController();
    setCommands([]);
    setSelected(null);
    setError(null);
    void api.get<BotCommand[]>(`/channels/${channelId}/bot-commands`, undefined, abort.signal).then((result) => { if (!abort.signal.aborted) setCommands(Array.isArray(result) ? result : []); }).catch((failure) => { if (!abort.signal.aborted) setError(failure); });
    return () => abort.abort();
  }, [channelId]);
  useEffect(() => setActive(0), [query]);
  const choose = (command: BotCommand) => { setSelected(command); setValues({}); setError(null); };
  useImperativeHandle(ref, () => ({
    openFirst: () => { if (suggestions[active] ?? suggestions[0]) choose(suggestions[active] ?? suggestions[0]); },
    keyDown: (key) => {
      if (selected) return false;
      if (!suggestions.length && key !== "Enter") return false;
      if (key === "ArrowDown" || key === "ArrowUp") {
        if (suggestions.length) setActive((index) => (index + (key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length);
        return true;
      }
      if (key === "Enter" || key === "Tab") {
        if (suggestions[active] ?? suggestions[0]) choose(suggestions[active] ?? suggestions[0]);
        return true;
      }
      return false;
    },
  }));
  const invoke = async () => {
    if (!selected || busy) return;
    const options: Record<string, string | number | boolean> = {};
    for (const option of selected.options) {
      const value = values[option.name];
      if (value === undefined || value === "") continue;
      options[option.name] = option.type === "bool" ? value === "true" : option.type === "int" ? Number(value) : value;
    }
    const abort = new AbortController();
    const timer = window.setTimeout(() => abort.abort(), 6000);
    setBusy(true);
    setError(null);
    try {
      await request(`/channels/${channelId}/interactions`, { method: "POST", body: { command_id: selected.id, options }, signal: abort.signal });
      setSelected(null);
      onComplete();
    } catch (failure) {
      setError(failure);
    } finally {
      window.clearTimeout(timer);
      setBusy(false);
    }
  };
  return <>
    <ul className="composer__mentions" role="listbox" aria-label={t("bots.slash_suggestions")}>
      {suggestions.map((command, index) => <li key={command.id} role="option" aria-selected={index === active}><button type="button" className={index === active ? "is-active" : ""} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(command)}><strong>/{command.name}</strong><span>{command.description}</span><span className="muted">{command.bot.display_name}</span><BotBadge isBot /></button></li>)}
      {suggestions.length === 0 ? <li className="muted">{t("bots.no_commands")}</li> : null}
    </ul>
    {!selected ? <ErrorText error={error} /> : null}
    {selected ? <Modal title={`/${selected.name} · ${selected.bot.display_name}`} onClose={busy ? () => undefined : () => setSelected(null)}>
      <p><BotBadge isBot /> {selected.description}</p><p className="notice">{t("bots.public_reply")}</p>
      <form onSubmit={(event) => { event.preventDefault(); void invoke(); }}>
        {selected.options.map((option) => option.type === "bool" ? <SelectField key={option.name} label={option.description} value={values[option.name] ?? ""} required={option.required} options={[{ value: "", label: t("bots.option_unset") }, { value: "true", label: t("bots.option_true") }, { value: "false", label: t("bots.option_false") }]} onChange={(event) => setValues((current) => ({ ...current, [option.name]: event.target.value }))} /> : <TextField key={option.name} label={option.description} hint={option.type === "user" || option.type === "channel" ? t("bots.option_id") : undefined} type={option.type === "int" ? "number" : "text"} step={option.type === "int" ? 1 : undefined} maxLength={option.type === "string" ? 1000 : 19} required={option.required} value={values[option.name] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [option.name]: event.target.value }))} />)}
        <ErrorText error={error} />
        {busy ? <p role="status">{t("bots.waiting")}</p> : null}
        <button type="submit" className="button button--primary" disabled={busy}>{t("bots.invoke")}</button>
      </form>
    </Modal> : null}
  </>;
});
