import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useMembers } from "../../api/hooks";
import { useAuth } from "../../store/auth";
import { useVoice } from "../../voice/useVoice";
import { Icon } from "../Icon";
import { Modal } from "../Modal";

export function VoiceDock() {
  const { t } = useTranslation();
  const voice = useVoice();
  const me = useAuth((state) => state.me);
  const [codesOpen, setCodesOpen] = useState(false);
  const members = useMembers(voice.serverId ?? undefined);
  const names: Record<string, string> = {};
  members.data?.members.forEach((member) => {
    names[member.user.id] = member.nickname ?? member.user.display_name;
  });

  if (!voice.room && !voice.ringing) {
    return null;
  }
  const peers = voice.participants.filter((p) => p.user_id !== me?.id);
  const label = voice.ringing && !voice.room ? t("voice.calling") : voice.conversationId ? t("voice.call_active") : t("voice.connected");
  return (
    <div className="voice-dock" role="region" aria-label={t("a11y.voice_controls")}>
      <div className="voice-dock__status">
        <span className="voice-dock__pulse" aria-hidden="true" />
        <div>
          <strong>{label}</strong>
          <p className="muted">{t("voice.participants", { count: voice.participants.length })}</p>
        </div>
      </div>
      <div className="voice-dock__buttons">
        <button type="button" className={`icon-button${voice.muted ? " is-off" : ""}`} onClick={voice.toggleMute} aria-pressed={voice.muted} aria-label={voice.muted ? t("voice.unmute") : t("voice.mute")} title={voice.muted ? t("voice.unmute") : t("voice.mute")}>
          <Icon name={voice.muted ? "micOff" : "mic"} />
        </button>
        <button type="button" className={`icon-button${voice.deafened ? " is-off" : ""}`} onClick={voice.toggleDeafen} aria-pressed={voice.deafened} aria-label={voice.deafened ? t("voice.undeafen") : t("voice.deafen")} title={voice.deafened ? t("voice.undeafen") : t("voice.deafen")}>
          <Icon name={voice.deafened ? "headphonesOff" : "headphones"} />
        </button>
        {peers.length > 0 ? (
          <button type="button" className="icon-button" onClick={() => setCodesOpen(true)} aria-label={t("voice.verify")} title={t("voice.verify")}>
            <Icon name="shield" />
          </button>
        ) : null}
        <button type="button" className="icon-button icon-button--danger" onClick={voice.leave} aria-label={t("voice.leave")} title={t("voice.leave")}>
          <Icon name="phoneOff" />
        </button>
      </div>
      {codesOpen ? (
        <Modal title={t("voice.verify_title")} onClose={() => setCodesOpen(false)}>
          <p>{t("voice.verify_explain")}</p>
          <ul className="code-list">
            {peers.map((peer) => (
              <li key={peer.user_id}>
                <span>{names[peer.user_id] ?? t("message.unknown_user")}</span>
                <code>{voice.codes[peer.user_id] ?? t("voice.verify_pending")}</code>
              </li>
            ))}
          </ul>
          <p className="muted">{t("voice.verify_note")}</p>
        </Modal>
      ) : null}
    </div>
  );
}
