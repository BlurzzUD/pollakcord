import { realtime } from "../realtime/socket";
import { securityCode } from "./securityCode";

export type VoiceErrorCode = "microphone_denied" | "microphone_unavailable";

export interface VoiceCallbacks {
  onSpeaking: (userId: string, speaking: boolean) => void;
  onSecurityCode: (userId: string, code: string) => void;
  onPeerState: (userId: string, state: RTCPeerConnectionState) => void;
}

interface Peer {
  userId: string;
  connection: RTCPeerConnection;
  audio: HTMLAudioElement;
  pendingIce: RTCIceCandidateInit[];
  hasRemote: boolean;
  analyser: AnalyserNode | null;
  speaking: boolean;
  quietSince: number;
}

const SPEAKING_THRESHOLD = 0.035;
const HANG_TIME_MS = 350;

function level(analyser: AnalyserNode, buffer: Uint8Array<ArrayBuffer>): number {
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for (const sample of buffer) {
    const centered = (sample - 128) / 128;
    sum += centered * centered;
  }
  return Math.sqrt(sum / buffer.length);
}

export class VoiceManager {
  private peers = new Map<string, Peer>();
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private localAnalyser: AnalyserNode | null = null;
  private localSpeaking = false;
  private localQuietSince = 0;
  private meterTimer: number | null = null;
  private muted = false;
  private deafened = false;
  private serverMuted = false;
  private blocked = new Set<string>();
  private selfId = "";

  constructor(
    private readonly callbacks: VoiceCallbacks,
    private iceServers: RTCIceServer[],
  ) {}

  async start(selfId: string): Promise<VoiceErrorCode | null> {
    this.selfId = selfId;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
    } catch (error) {
      const denied = error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
      return denied ? "microphone_denied" : "microphone_unavailable";
    }
    this.context = new AudioContext();
    this.localAnalyser = this.analyserFor(this.stream);
    this.applyLocalTrack();
    this.meterTimer = window.setInterval(() => this.measure(), 90);
    return null;
  }

  private analyserFor(stream: MediaStream): AnalyserNode | null {
    if (!this.context) {
      return null;
    }
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 512;
    this.context.createMediaStreamSource(stream).connect(analyser);
    return analyser;
  }

  private applyLocalTrack(): void {
    this.stream?.getAudioTracks().forEach((track) => {
      track.enabled = !this.muted && !this.deafened && !this.serverMuted;
    });
  }

  private measure(): void {
    const buffer = new Uint8Array(512);
    const now = performance.now();
    if (this.localAnalyser && this.stream?.getAudioTracks()[0]?.enabled) {
      const active = level(this.localAnalyser, buffer) > SPEAKING_THRESHOLD;
      this.updateSpeaking(this.selfId, active, now, "local");
    } else if (this.localSpeaking) {
      this.localSpeaking = false;
      this.callbacks.onSpeaking(this.selfId, false);
    }
    for (const peer of this.peers.values()) {
      if (!peer.analyser) {
        continue;
      }
      const active = !peer.audio.muted && level(peer.analyser, buffer) > SPEAKING_THRESHOLD;
      if (active) {
        peer.quietSince = now;
      }
      const speaking = active || now - peer.quietSince < HANG_TIME_MS;
      if (speaking !== peer.speaking) {
        peer.speaking = speaking;
        this.callbacks.onSpeaking(peer.userId, speaking);
      }
    }
  }

  private updateSpeaking(userId: string, active: boolean, now: number, kind: "local"): void {
    if (kind === "local") {
      if (active) {
        this.localQuietSince = now;
      }
      const speaking = active || now - this.localQuietSince < HANG_TIME_MS;
      if (speaking !== this.localSpeaking) {
        this.localSpeaking = speaking;
        this.callbacks.onSpeaking(userId, speaking);
      }
    }
  }

  private createPeer(userId: string): Peer {
    const existing = this.peers.get(userId);
    if (existing) {
      return existing;
    }
    const connection = new RTCPeerConnection({ iceServers: this.iceServers });
    const audio = new Audio();
    audio.autoplay = true;
    audio.muted = this.deafened || this.blocked.has(userId);
    const peer: Peer = { userId, connection, audio, pendingIce: [], hasRemote: false, analyser: null, speaking: false, quietSince: 0 };
    this.stream?.getTracks().forEach((track) => connection.addTrack(track, this.stream as MediaStream));
    connection.onicecandidate = (event) => {
      if (event.candidate) {
        realtime.send("voice.signal", { to: userId, kind: "ice", data: { candidate: event.candidate.toJSON() } });
      }
    };
    connection.ontrack = (event) => {
      const [remote] = event.streams;
      if (remote) {
        audio.srcObject = remote;
        peer.analyser = this.analyserFor(remote);
        void audio.play().catch(() => undefined);
      }
    };
    connection.onconnectionstatechange = () => {
      this.callbacks.onPeerState(userId, connection.connectionState);
      if (connection.connectionState === "connected") {
        void this.publishCode(peer);
      }
    };
    this.peers.set(userId, peer);
    return peer;
  }

  private async publishCode(peer: Peer): Promise<void> {
    const code = await securityCode(peer.connection.localDescription?.sdp, peer.connection.remoteDescription?.sdp);
    if (code) {
      this.callbacks.onSecurityCode(peer.userId, code);
    }
  }

  async connectTo(userId: string): Promise<void> {
    const peer = this.createPeer(userId);
    const offer = await peer.connection.createOffer();
    await peer.connection.setLocalDescription(offer);
    realtime.send("voice.signal", { to: userId, kind: "offer", data: { description: { type: offer.type, sdp: offer.sdp } } });
  }

  async handleSignal(from: string, kind: string, data: { description?: RTCSessionDescriptionInit; candidate?: RTCIceCandidateInit }): Promise<void> {
    if (kind === "offer" && data.description) {
      const peer = this.createPeer(from);
      await peer.connection.setRemoteDescription(data.description);
      peer.hasRemote = true;
      await this.flushIce(peer);
      const answer = await peer.connection.createAnswer();
      await peer.connection.setLocalDescription(answer);
      realtime.send("voice.signal", { to: from, kind: "answer", data: { description: { type: answer.type, sdp: answer.sdp } } });
      return;
    }
    const peer = this.peers.get(from);
    if (!peer) {
      return;
    }
    if (kind === "answer" && data.description) {
      await peer.connection.setRemoteDescription(data.description);
      peer.hasRemote = true;
      await this.flushIce(peer);
    } else if (kind === "ice" && data.candidate) {
      if (peer.hasRemote) {
        await peer.connection.addIceCandidate(data.candidate).catch(() => undefined);
      } else {
        peer.pendingIce.push(data.candidate);
      }
    }
  }

  private async flushIce(peer: Peer): Promise<void> {
    const queued = peer.pendingIce.splice(0);
    for (const candidate of queued) {
      await peer.connection.addIceCandidate(candidate).catch(() => undefined);
    }
  }

  removePeer(userId: string): void {
    const peer = this.peers.get(userId);
    if (!peer) {
      return;
    }
    peer.connection.close();
    peer.audio.srcObject = null;
    this.peers.delete(userId);
    this.callbacks.onSpeaking(userId, false);
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.applyLocalTrack();
  }

  setDeafened(deafened: boolean): void {
    this.deafened = deafened;
    this.applyLocalTrack();
    this.peers.forEach((peer) => {
      peer.audio.muted = deafened || this.blocked.has(peer.userId);
    });
  }

  setServerMuted(serverMuted: boolean): void {
    this.serverMuted = serverMuted;
    this.applyLocalTrack();
  }

  setBlocked(userIds: Set<string>): void {
    this.blocked = userIds;
    this.peers.forEach((peer) => {
      peer.audio.muted = this.deafened || userIds.has(peer.userId);
    });
  }

  stop(): void {
    this.peers.forEach((_, userId) => this.removePeer(userId));
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    if (this.meterTimer !== null) {
      window.clearInterval(this.meterTimer);
      this.meterTimer = null;
    }
    void this.context?.close().catch(() => undefined);
    this.context = null;
    this.localAnalyser = null;
    this.callbacks.onSpeaking(this.selfId, false);
  }
}
