import { $ } from "./dom.mjs";
import { base64ToBlob, blobToBase64 } from "./audio-utils.mjs";
import { currentUiLocale, translate } from "../i18n.js";

export function createConversationAudio({
  captureProjectScope, cleanAssistantText, conversationLanguage, conversationMessage, isCurrentProjectScope,
  render, sendChatMessage, state, storyApi, toast
}) {
  async function speakText(text) {
    if (state.voiceMode) return;
    state.audioPlayer?.pause();
    const scope = captureProjectScope();
    try {
      // Speak the exact chosen visible reply, including when the optional legacy
      // memory-session question differs from the collector's current question.
      const generated = await storyApi("/v1/story/question-audio", {
        method:"POST", body:JSON.stringify({text:cleanAssistantText(text), language:conversationLanguage()}),
      });
      if (isCurrentProjectScope(scope)) await playGeneratedAudio(generated);
      return;
    } catch (error) {
      if (!isCurrentProjectScope(scope)) return;
      if (error.status !== 503) toast(error.message);
    }
    if (!window.speechSynthesis) return toast(translate("Memoir.storyFlow.readAloudUnavailable"));
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = currentUiLocale();
    utterance.rate = 0.96;
    utterance.onend = () => { state.speaking = false; };
    state.speaking = true;
    window.speechSynthesis.speak(utterance);
  }

  function setVoiceOrbLevel(level) {
    const orb = document.querySelector(".voice-orb");
    if (!orb) return;
    const value = Math.min(1, Math.max(0, level));
    orb.style.setProperty("--voice-level", value.toFixed(3));
  }

  function monitorVoicePlayback(player) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!state.voiceMode || !AudioContextCtor) return () => {};
    let context;
    let frame;
    try {
      context = new AudioContextCtor();
      const source = context.createMediaElementSource(player);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(context.destination);
      const samples = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(samples);
        const energy = samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0);
        setVoiceOrbLevel(Math.sqrt(energy / samples.length) * 5);
        frame = window.requestAnimationFrame(tick);
      };
      context.resume().catch(() => {});
      frame = window.requestAnimationFrame(tick);
    } catch {
      context?.close().catch(() => {});
      return () => {};
    }
    return () => {
      window.cancelAnimationFrame(frame);
      context.close().catch(() => {});
      setVoiceOrbLevel(0);
    };
  }

  function playGeneratedAudio(generated) {
    if (!generated?.audio_base64) return Promise.reject(new Error("Generated audio was empty."));
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(base64ToBlob(generated.audio_base64, generated.mime_type || "audio/mpeg"));
      const player = new Audio(url);
      let settled = false;
      const stopMonitor = monitorVoicePlayback(player);
      const finish = (error) => {
        if (settled) return;
        settled = true;
        stopMonitor();
        URL.revokeObjectURL(url);
        player.onended = null;
        player.onerror = null;
        if (state.audioPlayer === player) state.audioPlayer = null;
        if (state.voiceModePlaybackFinish === finish) state.voiceModePlaybackFinish = null;
        if (error) reject(error);
        else resolve();
      };
      state.audioPlayer = player;
      state.voiceModePlaybackFinish = finish;
      player.onended = () => finish();
      player.onerror = () => finish(new Error("Generated audio could not be played."));
      player.play().catch(finish);
    });
  }

  async function speakVoiceReply(text) {
    if (!state.voiceMode || !text) return;
    const turnId = state.voiceModeTurnId;
    state.voiceModeStatus = "speaking";
    render();
    try {
      const generated = await storyApi("/v1/story/question-audio", {
        method: "POST",
        body: JSON.stringify({
          text,
          language: conversationLanguage(),
        }),
      });
      if (state.voiceMode && state.voiceModeTurnId === turnId) await playGeneratedAudio(generated);
    } catch (error) {
      if (!state.voiceMode || state.voiceModeTurnId !== turnId) return;
      // Browser default voices can change Mira's identity between conversation turns.
      toast(conversationMessage("voicePlaybackUnavailable"));
    }
  }

  function clearVoiceModeCapture() {
    if (state.voiceModeMonitor) window.cancelAnimationFrame(state.voiceModeMonitor);
    state.voiceModeMonitor = null;
    if (state.voiceModeAudioContext) state.voiceModeAudioContext.close().catch(() => {});
    state.voiceModeAudioContext = null;
    state.voiceModeAnalyser = null;
  }

  function stopVoiceMode({ silent = false } = {}) {
    if (state.pendingAudioUpload) state.pendingAudioUpload.cancelled = true;
    const active = Boolean(state.voiceMode || state.voiceModeRecorder || state.voiceModeStream);
    state.voiceMode = false;
    state.voiceModeStatus = "off";
    state.voiceMuted = false;
    state.voiceModeCancelTurn = true;
    state.voiceModeTurnId += 1;
    clearVoiceModeCapture();
    if (state.voiceModeRecorder && state.voiceModeRecorder.state !== "inactive") {
      try { state.voiceModeRecorder.stop(); } catch { /* recorder is already closing */ }
    }
    state.voiceModeStream?.getTracks().forEach((track) => track.stop());
    state.voiceModeStream = null;
    state.voiceModeRecorder = null;
    state.audioPlayer?.pause();
    state.voiceModePlaybackFinish?.();
    state.voiceModePlaybackFinish = null;
    window.speechSynthesis?.cancel();
    if (active && !silent) toast(translate("Memoir.storyFlow.voiceEnded"));
    if (active) render();
  }

  function queueVoiceModeTurn(delay = 260) {
    window.setTimeout(() => {
      if (state.voiceMode && !state.loading && !state.voiceModeRecorder) startVoiceModeTurn();
    }, delay);
  }

  function monitorVoiceActivity(stream, recorder, turnId) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return;
    try {
      const context = new AudioContextCtor();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const startedAt = performance.now();
      let speechDetected = false;
      let quietSince = 0;
      state.voiceModeAudioContext = context;
      state.voiceModeAnalyser = analyser;
      context.resume().catch(() => {});

      const tick = () => {
        if (!state.voiceMode || state.voiceModeTurnId !== turnId || state.voiceModeRecorder !== recorder || recorder.state === "inactive") return;
        if (state.voiceMuted) {
          setVoiceOrbLevel(0);
          quietSince = 0;
          state.voiceModeMonitor = window.requestAnimationFrame(tick);
          return;
        }
        analyser.getByteTimeDomainData(samples);
        let energy = 0;
        for (const sample of samples) {
          const normalized = (sample - 128) / 128;
          energy += normalized * normalized;
        }
        const rms = Math.sqrt(energy / samples.length);
        setVoiceOrbLevel(rms * 5);
        const now = performance.now();
        if (rms > 0.035) {
          speechDetected = true;
          quietSince = 0;
        } else if (speechDetected && now - startedAt > 700) {
          quietSince ||= now;
          if (now - quietSince > 1200) {
            recorder.stop();
            return;
          }
        }
        if (now - startedAt > 60_000) {
          recorder.stop();
          return;
        }
        state.voiceModeMonitor = window.requestAnimationFrame(tick);
      };
      state.voiceModeMonitor = window.requestAnimationFrame(tick);
    } catch {
      // MediaRecorder still works without activity detection; the user can end the mode manually.
    }
  }

  async function startVoiceModeTurn() {
    if (!state.voiceMode || state.voiceMuted || state.loading || state.voiceModeRecorder) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      state.voiceMode = false;
      state.voiceModeStatus = "off";
      render();
      return toast(translate("Memoir.storyFlow.voiceConversationUnavailable"));
    }
    const turnId = state.voiceModeTurnId += 1;
    state.voiceModeCancelTurn = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!state.voiceMode || state.voiceModeTurnId !== turnId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      state.voiceModeStream = stream;
      stream.getTracks().forEach((track) => { track.enabled = !state.voiceMuted; });
      const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
      const recorder = preferredMime ? new MediaRecorder(stream, { mimeType: preferredMime }) : new MediaRecorder(stream);
      state.voiceModeRecorder = recorder;
      const chunks = [];
      state.voiceModeStatus = "listening";
      recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
      recorder.addEventListener("stop", async () => {
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        if (state.voiceModeTurnId === turnId) clearVoiceModeCapture();
        stream.getTracks().forEach((track) => track.stop());
        if (state.voiceModeRecorder === recorder) state.voiceModeRecorder = null;
        if (state.voiceModeStream === stream) state.voiceModeStream = null;
        const cancelled = state.voiceModeCancelTurn || !state.voiceMode || state.voiceModeTurnId !== turnId;
        state.voiceModeCancelTurn = false;
        if (cancelled || !blob.size) {
          if (state.voiceMode) render();
          return;
        }
        state.voiceModeStatus = "processing";
        render();
        try {
          const saved = await transcribeRecordedAudio(blob, `voice-${Date.now()}`);
          if (!state.voiceMode || state.voiceModeTurnId !== turnId) return;
          if (!state.voiceMode || state.voiceModeTurnId !== turnId || !saved.text) {
            if (state.voiceMode) {
              state.voiceModeStatus = "listening";
              render();
              queueVoiceModeTurn();
            }
            return;
          }
          state.audioRecordings = [...(state.audioRecordings || []), saved.recording];
          state.audioUploadId = saved.uploadId;
          state.audioTranscript = saved.text;
          state.audioTranscriptKind = "narrator_transcript";
          state.photoTurns?.saveAudioDraft();
          await sendChatMessage({ voiceTurn: true });
        } catch (error) {
          if (state.voiceMode) {
            toast(error.message || conversationMessage("voiceAnswerFailed"));
            state.voiceMode = false;
            state.voiceModeStatus = "off";
            render();
          }
        }
      });
      recorder.start();
      render();
      monitorVoiceActivity(stream, recorder, turnId);
    } catch {
      state.voiceMode = false;
      state.voiceModeStatus = "off";
      state.voiceModeRecorder = null;
      state.voiceModeStream = null;
      render();
      toast(translate("Memoir.storyFlow.microphoneUnavailable"));
    }
  }

  function toggleVoiceInput() {
    if (!state.voiceMode && state.pendingAudioUpload) { void startAudioRecorder(); return; }
    if (state.voiceMode) {
      stopVoiceMode();
      return;
    }
    if (state.loading || state.photoMemoryTask || state.dictationStatus !== "off") return;
    state.voiceMode = true;
    state.voiceModeStatus = "listening";
    state.voiceModeCancelTurn = false;
    render();
    startVoiceModeTurn();
  }

  function clearDictationMonitor() {
    if (state.dictationMonitor !== null) window.cancelAnimationFrame(state.dictationMonitor);
    state.dictationMonitor = null;
    state.dictationAudioContext?.close().catch(() => {});
    state.dictationAudioContext = null;
  }

  function monitorDictation(stream, id) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return;
    try {
      const context = new AudioContextCtor();
      state.dictationAudioContext = context;
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaStreamSource(stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      const levels = Array(40).fill(0);
      const tick = () => {
        if (state.dictationId !== id || !state.recording) return;
        analyser.getByteTimeDomainData(samples);
        const energy = samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0);
        levels.push(Math.min(1, Math.sqrt(energy / samples.length) * 5));
        levels.shift();
        document.querySelectorAll(".dictation-wave i").forEach((bar, i) => {
          bar.style.height = `${3 + levels[i] * 23}px`;
        });
        state.dictationMonitor = window.requestAnimationFrame(tick);
      };
      context.resume().catch(() => {});
      state.dictationMonitor = window.requestAnimationFrame(tick);
    } catch {
      clearDictationMonitor();
    }
  }

  function cancelDictation() {
    if (state.pendingAudioUpload) { state.pendingAudioUpload.cancelled = true; void discardAudioDraft({pendingOnly:true}); }
    clearDictationMonitor();
    state.dictationId += 1;
    state.dictationStatus = "off";
    state.recording = false;
    if (state.recorder?.state !== "inactive") state.recorder?.stop();
    state.recordingStream?.getTracks().forEach((track) => track.stop());
    state.recordingStream = null;
    state.recorder = null;
    state.recordedChunks = [];
    render();
  }

  async function finishDictation(send) {
    if (state.dictationStatus !== "recording" && state.dictationStatus !== "stopped") return;
    state.dictationSend = send;
    state.dictationStatus = "processing";
    clearDictationMonitor();
    if (state.recording) {
      state.recorder.stop();
      render();
      return;
    }
    await transcribeDictation(state.dictationId);
  }

  async function transcribeDictation(id) {
    render();
    let shouldSend = false;
    try {
      const blob = new Blob(state.recordedChunks, { type: state.recorder?.mimeType || "audio/webm" });
      if (!blob.size) return;
      const saved = await transcribeRecordedAudio(blob, `dictation-${Date.now()}`);
      if (state.dictationId !== id) return;
      if (state.dictationId !== id) return;
      state.audioRecordings = [...(state.audioRecordings || []), saved.recording];
      state.audioTranscript = [state.audioTranscript.trim(), saved.text].filter(Boolean).join(" ");
      state.audioTranscriptKind = "narrator_transcript";
      state.photoTurns?.saveAudioDraft();
      shouldSend = state.dictationSend && Boolean(saved.text);
    } catch (error) { if (state.dictationId === id) toast(error.message); }
    finally {
      if (state.dictationId === id) {
        state.dictationStatus = "off";
        state.recorder = null;
        state.recordedChunks = [];
        render();
        $("#chat-input")?.focus();
      }
    }
    if (shouldSend && state.dictationId === id) await sendChatMessage();
  }

  async function startAudioRecorder() {
    if (state.loading || state.voiceMode || state.dictationStatus !== "off") return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast(translate("Memoir.storyFlow.browserCannotRecord"));
    if (state.pendingAudioUpload) {
      const pending = state.pendingAudioUpload;
      state.dictationStatus = 'processing'; render();
      try {
        const saved = await transcribeRecordedAudio(pending.blob, pending.filenamePrefix);
        state.audioRecordings = [...(state.audioRecordings || []), saved.recording];
        state.audioTranscript = [state.audioTranscript.trim(),saved.text].filter(Boolean).join(' ');
        state.audioTranscriptKind = 'narrator_transcript';
        state.photoTurns?.saveAudioDraft();
      } catch (error) { toast(error.message); }
      finally { state.dictationStatus = 'off'; render(); }
      return;
    }
    const id = ++state.dictationId;
    state.dictationStatus = "starting";
    render();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (state.dictationId !== id) { stream.getTracks().forEach((track) => track.stop()); return; }
      state.recordingStream = stream;
      const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
      const recorder = preferredMime ? new MediaRecorder(stream, { mimeType: preferredMime }) : new MediaRecorder(stream);
      state.recorder = recorder;
      state.recordedChunks = [];
      recorder.addEventListener("dataavailable", (event) => { if (state.dictationId === id && event.data.size) state.recordedChunks.push(event.data); });
      recorder.addEventListener("stop", () => {
        stream.getTracks().forEach((track) => track.stop());
        if (state.dictationId !== id) return;
        clearDictationMonitor();
        state.recordingStream = null;
        state.recording = false;
        if (state.dictationStatus === "processing") transcribeDictation(id);
        else render();
      });
      recorder.start();
      state.recording = true;
      state.dictationStatus = "recording";
      render();
      monitorDictation(stream, id);
    } catch {
      stream?.getTracks().forEach((track) => track.stop());
      if (state.dictationId !== id) return;
      state.dictationStatus = "off";
      state.recorder = null;
      state.recordingStream = null;
      render();
      toast(translate("Memoir.storyFlow.microphoneUnavailable"));
    }
  }

  async function transcribeRecordedAudio(blob, filenamePrefix) {
    const scope = captureProjectScope();
    const pending = state.pendingAudioUpload?.blob === blob ? state.pendingAudioUpload :
      {blob, filenamePrefix, scope, uploadKey:globalThis.crypto.randomUUID()};
    if (!isCurrentProjectScope(pending.scope)) throw new Error('Recording owner changed');
    state.pendingAudioUpload = pending;
    state.photoTurns?.saveAudioDraft();
    if (!blob && pending.backendSaved === false) throw new Error('Upload was not confirmed; discard this incomplete draft before retaking.');
    const encoded = pending.recordingId ? null : await blobToBase64(blob);
    if (!isCurrentProjectScope(scope)) throw new Error('Recording owner changed');
    if (pending.cancelled) throw new Error('Recording discarded');
    const mimeType = (blob?.type || "audio/webm").split(";")[0];
    const extension = mimeType === "audio/mp4" ? "mp4" : "webm";
    try {
      const transcript = await storyApi("/v1/story/transcriptions", {
        method: "POST",
        body: JSON.stringify(pending.recordingId ? {recording_id:pending.recordingId,project_id:scope.projectId || null,language:conversationLanguage()} :
          {audio_base64:encoded, upload_idempotency_key:pending.uploadKey, project_id:scope.projectId || null,
            filename:`${filenamePrefix}.${extension}`, mime_type:mimeType, language:conversationLanguage()}),
      });
      if (!isCurrentProjectScope(scope)) throw new Error('Recording owner changed');
      if (!transcript.recording?.backend_saved || transcript.recording.storage_status !== 'ready')
        throw new Error('Backend original was not confirmed saved');
      if (pending.cancelled) {
        pending.recordingId = transcript.recording.id;
        await storyApi('/v1/story/recordings/' + encodeURIComponent(transcript.recording.id) + '?draft_only=true', {method:'DELETE'});
        state.pendingAudioUpload = null;
        throw new Error('Recording discarded');
      }
      state.pendingAudioUpload = null;
      return {uploadId:null, recording:transcript.recording, text:String(transcript.text || '').trim(), language:transcript.source?.language || ''};
    } catch (error) {
      if (isCurrentProjectScope(scope) && error.detail?.backend_saved && error.detail?.recording_id)
        pending.recordingId = error.detail.recording_id;
      if (isCurrentProjectScope(scope)) state.photoTurns?.saveAudioDraft();
      throw error;
    }
  }

  async function discardAudioDraft({pendingOnly=false} = {}) {
    const scope = captureProjectScope();
    const pending = state.pendingAudioUpload;
    if (pending && !isCurrentProjectScope(pending.scope)) return;
    if (pending) pending.cancelled = true;
    try {
      const ids = pendingOnly ? [] : (state.audioRecordings || []).map(recording => recording.id);
      if (pending?.recordingId) ids.push(pending.recordingId);
      else if (pending?.uploadKey) {
        try {
          const found = await storyApi('/v1/story/recordings/by-upload/' + encodeURIComponent(pending.uploadKey));
          if (!isCurrentProjectScope(scope)) return;
          ids.push(found.recording.id);
        } catch (error) { if (error.status !== 404) throw error; }
      }
      for (const id of new Set(ids)) {
        if (!isCurrentProjectScope(scope)) return;
        await storyApi('/v1/story/recordings/' + encodeURIComponent(id) + '?draft_only=true', {method:'DELETE'});
      }
      if (!isCurrentProjectScope(scope)) return;
      if (!pendingOnly) { state.audioRecordings = []; state.audioTranscriptKind = 'narrator_chat'; }
      if (state.pendingAudioUpload === pending) state.pendingAudioUpload = null;
      state.photoTurns?.saveAudioDraft();
      render();
    } catch (error) { if (isCurrentProjectScope(scope)) toast(error.message); }
  }

  return {
    cancelDictation, discardAudioDraft, finishDictation, queueVoiceModeTurn, speakText, speakVoiceReply, startAudioRecorder,
    startVoiceModeTurn, stopVoiceMode, toggleVoiceInput
  };
}
