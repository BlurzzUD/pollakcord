import { useTranslation } from "react-i18next";

import type { Channel, Member, ServerDetail } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { realtime } from "../../realtime/socket";
import { useAuth } from "../../store/auth";
import { useLive } from "../../store/live";
import { can } from "../../utils/permissions";
import { useVoice } from "../../voice/useVoice";

export function VoiceRoomView({ channel, server, members }: { channel: Channel; server: ServerDetail; members: Member[] }) {
  const { t } = useTranslation();
  const meId = useAuth((state) => state.me?.id);
  const voice = useVoice();
  const live = useLive((state) => state.voiceStates[channel.id]);
  const participants = live ?? server.voice_states[channel.id] ?? [];
  const joined = voice.channelId === channel.id;
  const byId = new Map(members.map((member) => [member.user.id, member]));
  const canMute = can(channel.my_permissions, "mute_members");
  const canDeafen = can(channel.my_permissions, "deafen_members");
  const canConnect = can(channel.my_permissions, "connect");

  return (
    <div className="voice-room">
      <div className="voice-room__grid">
        {participants.length === 0 ? <p className="muted">{t("voice.empty_room")}</p> : null}
        {participants.map((participant) => {
          const member = byId.get(participant.user_id);
          const name = member?.nickname ?? member?.user.display_name ?? t("message.unknown_user");
          const speaking = voice.speaking[participant.user_id];
          return (
            <div key={participant.user_id} className={`voice-tile${speaking ? " is-speaking" : ""}`}>
              <Avatar name={name} url={member?.user.avatar_url} size={72} />
              <strong>{name}</strong>
              <div className="voice-tile__state">
                {participant.muted || participant.server_muted ? <Icon name="micOff" size={16} label={t("voice.muted")} /> : null}
                {participant.deafened || participant.server_deafened ? <Icon name="headphonesOff" size={16} label={t("voice.deafened")} /> : null}
                {speaking ? <span className="sr-only">{t("voice.speaking")}</span> : null}
              </div>
              {participant.user_id !== meId && (canMute || canDeafen) ? (
                <div className="voice-tile__tools">
                  {canMute ? (
                    <button type="button" className="button button--small button--ghost" onClick={() => realtime.send("voice.moderate", { channel_id: channel.id, user_id: participant.user_id, server_muted: !participant.server_muted })}>
                      {participant.server_muted ? t("voice.server_unmute") : t("voice.server_mute")}
                    </button>
                  ) : null}
                  {canDeafen ? (
                    <button type="button" className="button button--small button--ghost" onClick={() => realtime.send("voice.moderate", { channel_id: channel.id, user_id: participant.user_id, server_deafened: !participant.server_deafened })}>
                      {participant.server_deafened ? t("voice.server_undeafen") : t("voice.server_deafen")}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="voice-room__controls">
        {joined ? (
          <>
            <button type="button" className={`button ${voice.muted ? "button--danger" : "button--outline"}`} onClick={voice.toggleMute} aria-pressed={voice.muted}>
              <Icon name={voice.muted ? "micOff" : "mic"} /> {voice.muted ? t("voice.unmute") : t("voice.mute")}
            </button>
            <button type="button" className={`button ${voice.deafened ? "button--danger" : "button--outline"}`} onClick={voice.toggleDeafen} aria-pressed={voice.deafened}>
              <Icon name={voice.deafened ? "headphonesOff" : "headphones"} /> {voice.deafened ? t("voice.undeafen") : t("voice.deafen")}
            </button>
            <button type="button" className="button button--danger" onClick={voice.leave}>
              <Icon name="phoneOff" /> {t("voice.leave")}
            </button>
          </>
        ) : (
          <button type="button" className="button button--primary button--large" onClick={() => voice.joinChannel(channel.id)} disabled={!canConnect}>
            <Icon name="volume" /> {t("voice.join")}
          </button>
        )}
      </div>
      <p className="notice">
        <Icon name="lock" size={16} /> {t("voice.e2e_note")}
      </p>
    </div>
  );
}
