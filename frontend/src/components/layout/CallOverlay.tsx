import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useLive } from "../../store/live";
import { useVoice } from "../../voice/useVoice";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";

export function CallOverlay() {
  const { t } = useTranslation();
  const call = useLive((state) => state.incomingCall);
  const setIncoming = useLive((state) => state.setIncomingCall);
  const acceptCall = useVoice((state) => state.acceptCall);
  const declineCall = useVoice((state) => state.declineCall);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!call) {
      return;
    }
    const interval = window.setInterval(() => {
      setTick((value) => value + 1);
      if (Date.now() > call.expiresAt) {
        setIncoming(null);
      }
    }, 1000);
    return () => window.clearInterval(interval);
  }, [call, setIncoming]);

  if (!call) {
    return null;
  }
  return (
    <div className="call-overlay" role="alertdialog" aria-labelledby="call-title" aria-live="assertive">
      <Avatar name={call.from.display_name} url={call.from.avatar_url} size={56} />
      <div>
        <strong id="call-title">{call.from.display_name}</strong>
        <p className="muted">{t("voice.incoming_call")}</p>
      </div>
      <button type="button" className="button button--primary" onClick={() => acceptCall(call.conversationId)} data-autofocus>
        <Icon name="phone" /> {t("voice.accept")}
      </button>
      <button type="button" className="button button--danger" onClick={() => declineCall(call.conversationId)}>
        <Icon name="phoneOff" /> {t("voice.decline")}
      </button>
    </div>
  );
}
