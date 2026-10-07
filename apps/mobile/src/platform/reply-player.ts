export interface SpokenReply {
  audio_base64: string;
  mime_type: string;
}
export interface ReplyPlayerPort {
  generate(text: string, language: string): Promise<SpokenReply>;
  play(reply: SpokenReply, isCurrent: () => boolean): Promise<void>;
  stop(): Promise<void>;
}
/** Deliberate playback only. A late provider response cannot restart stopped audio. */
export function createReplyPlayer(port: ReplyPlayerPort) {
  let epoch = 0;
  let busy = false;
  return {
    isBusy: () => busy,
    async play(text: string, language: string) {
      if (!text.trim() || text.length > 4096)
        throw new Error("Speech requires between 1 and 4096 characters");
      const id = ++epoch;
      busy = true;
      try {
        await port.stop();
        if (id !== epoch) return;
        const reply = await port.generate(text, language);
        if (id !== epoch) return;
        if (
          !["audio/mpeg", "audio/mp3", "audio/mp4", "audio/wav"].includes(
            reply.mime_type,
          ) ||
          reply.audio_base64.length > 8 * 1024 * 1024
        )
          throw new Error("Unsupported spoken reply");
        await port.play(reply, () => id === epoch);
      } finally {
        if (id === epoch) busy = false;
      }
    },
    async stop() {
      epoch++;
      busy = false;
      await port.stop();
    },
  };
}
