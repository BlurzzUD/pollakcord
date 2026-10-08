import { create } from "zustand";

import { api } from "../api/client";
import type { IceConfig, Id, VoiceParticipant } from "../api/types";
import { realtime } from "../realtime/socket";
import { useAuth } from "../store/auth";
import { useLive } from "../store/live";
import { useUi } from "../store/ui";
import i18n from "../i18n";
import { VoiceManager, type VoiceErrorCode } from "./VoiceManager";

interface VoiceState {
  room: string | null;
  channelId: Id | null;
  serverId: Id | null;
  conversationId: Id | null;
  participants: VoiceParticipant[];
  muted: boolean;
  deafened: boolean;
  speaking: Record<Id, boolean>;
  codes: Record<Id, string>;
  peerStates: Record<Id, RTCPeerConnectionState>;
  ringing: boolean;
  joinChannel: (channelId: Id) => void;
  startCall: (conversationId: Id) => void;
  acceptCall: (conversationId: Id) => void;
  declineCall: (conversationId: Id) => void;
  leave: () => void;
  toggleMute: () => void;
  toggleDeafen: () => void;
}

let manager: VoiceManager | null = null;

const EMPTY = { room: null, channelId: null, serverId: null, conversationId: null, participants: [], speaking: {}, codes: {}, peerStates: {}, ringing: false };

export const useVoice = create<VoiceState>((set, get) => ({
  ...EMPTY,
  muted: false,
  deafened: false,
  joinChannel: (channelId) => {
    realtime.send("voice.join", { channel_id: channelId });
  },
  startCall: (conversationId) => {
    realtime.send("call.invite", { conversation_id: conversationId });
    set({ ringing: true, conversationId });
  },
  acceptCall: (conversationId) => {
    realtime.send("call.accept", { conversation_id: conversationId });
    useLive.getState().setIncomingCall(null);
  },
  declineCall: (conversationId) => {
    realtime.send("call.decline", { conversation_id: conversationId });
    useLive.getState().setIncomingCall(null);
  },
  leave: () => {
    const { ringing, conversationId, room } = get();
    if (ringing && conversationId && !room) {
      realtime.send("call.cancel", { conversation_id: conversationId });
    } else {
      realtime.send("voice.leave");
    }
    teardown();
  },
  toggleMute: () => {
    const muted = !get().muted;
    manager?.setMuted(muted);
    set({ muted });
    realtime.send("voice.state", { muted, deafened: get().deafened });
  },
  toggleDeafen: () => {
    const deafened = !get().deafened;
    manager?.setDeafened(deafened);
    set({ deafened });
    realtime.send("voice.state", { muted: get().muted, deafened });
  },
}));

function teardown(): void {
  manager?.stop();
  manager = null;
  useVoice.setState({ ...EMPTY, muted: false, deafened: false });
}

function applyPolicies(participants: VoiceParticipant[]): void {
  const me = useAuth.getState().me;
  const blocked = new Set(participants.filter((p) => p.server_muted && p.user_id !== me?.id).map((p) => p.user_id));
  manager?.setBlocked(blocked);
  manager?.setServerMuted(participants.some((p) => p.user_id === me?.id && p.server_muted));
}

function reportVoiceError(code: VoiceErrorCode): void {
  useUi.getState().push("error", i18n.t(`voice.${code}`));
}

async function onJoined(data: { room: string; channel_id: Id | null; server_id: Id | null; participants: VoiceParticipant[]; you: Id }): Promise<void> {
  const config = await api.get<IceConfig>("/rtc/config").catch(() => ({ ice_servers: [] as RTCIceServer[], max_participants: 8 }));
  manager?.stop();
  manager = new VoiceManager(
    {
      onSpeaking: (userId, speaking) => useVoice.setState((s) => ({ speaking: { ...s.speaking, [userId]: speaking } })),
      onSecurityCode: (userId, code) => useVoice.setState((s) => ({ codes: { ...s.codes, [userId]: code } })),
      onPeerState: (userId, state) => useVoice.setState((s) => ({ peerStates: { ...s.peerStates, [userId]: state } })),
    },
    config.ice_servers,
  );
  const conversationId = data.room.startsWith("dm:") ? data.room.slice(3) : null;
  useVoice.setState({ room: data.room, channelId: data.channel_id, serverId: data.server_id, conversationId, participants: data.participants, ringing: false });
  const failure = await manager.start(data.you);
  if (failure) {
    reportVoiceError(failure);
    realtime.send("voice.leave");
    teardown();
    return;
  }
  const { muted, deafened } = useVoice.getState();
  manager.setMuted(muted);
  manager.setDeafened(deafened);
  applyPolicies(data.participants);
  for (const participant of data.participants) {
    if (participant.user_id !== data.you) {
      await manager.connectTo(participant.user_id);
    }
  }
}

export function initVoiceController(): () => void {
  const subscriptions = [
    realtime.on("voice.joined", (data) => void onJoined(data)),
    realtime.on("voice.participant_joined", (data: { participants: VoiceParticipant[] }) => {
      useVoice.setState({ participants: data.participants });
      applyPolicies(data.participants);
    }),
    realtime.on("voice.participant_left", (data: { user_id: Id }) => {
      manager?.removePeer(data.user_id);
      useVoice.setState((s) => ({ participants: s.participants.filter((p) => p.user_id !== data.user_id) }));
    }),
    realtime.on("voice.state", (data: { room: string; participants: VoiceParticipant[] }) => {
      if (data.room === useVoice.getState().room) {
        useVoice.setState({ participants: data.participants });
        applyPolicies(data.participants);
      }
    }),
    realtime.on("voice.signal", (data: { from: Id; kind: string; data: never }) => {
      void manager?.handleSignal(data.from, data.kind, data.data);
    }),
    realtime.on("voice.disconnected", () => teardown()),
    realtime.on("call.ended", () => {
      teardown();
      useLive.getState().setIncomingCall(null);
    }),
    realtime.on("voice.channel_update", (data: { channel_id: Id; participants: VoiceParticipant[] }) => {
      useLive.getState().setVoiceChannel(data.channel_id, data.participants);
    }),
    realtime.on("socket.close", () => {
      if (useVoice.getState().room) {
        teardown();
      }
    }),
  ];
  return () => {
    subscriptions.forEach((off) => off());
    teardown();
  };
}
