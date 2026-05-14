import { useEffect, useRef, useState } from "react";
import { X, PhoneCall, Loader2 } from "lucide-react";
import { ProfessorCard } from "./components/ProfessorCard";
import { Button } from "./components/ui/button";
import {
  CALL_AUDIO_CONFIG,
  arrayBufferToBase64,
  createUtteranceBuffer,
  downmixToMono,
  encodeWavPcm16Mono,
  resetUtteranceBuffer,
  rmsFloat32,
  utteranceAppend,
  utteranceDrainAll,
  utteranceTake,
  type UtteranceBuffer
} from "@/lib/callAudio";

const PROFESSORS = [
  {
    id: "geddo",
    name: "Dr. Alaa Hamdy",
    initials: "AH",
    description: "A virtual professor in computer science and AI, explaining difficult concepts in a calm and clear way.",
    audioSrc: "/audio/geddo.wav",
    avatarSrc: "/avatars/alaa.jpg"
  },
  {
    id: "hammad",
    name: "Dr. Sherif Hammad",
    initials: "SH",
    description: "A virtual professor specialized in software engineering and algorithms, focused on practical step-by-step solutions.",
    audioSrc: "/audio/hammad.wav",
    avatarSrc: "/avatars/hammad.jpg"
  },
  {
    id: "hanan",
    name: "Dr. Hanan Hindy",
    initials: "HH",
    description: "A virtual professor in machine learning and data science, providing concise, organized, and practical answers.",
    audioSrc: "/audio/hanan.wav",
    avatarSrc: "/avatars/hanan.jpg"
  },
  {
    id: "mk",
    name: "Dr. Mahmoud Khalil",
    initials: "MK",
    description: "A virtual professor in robotics and cyber-physical systems, answering with an analytical style that connects theory to practice.",
    audioSrc: "/audio/mk.wav",
    avatarSrc: "/avatars/mk.jpg"
  }
];

const CALL_WS_URL = "";
/** Dev + local mock WS: plays a WAV on each `complete`. Set VITE_MOCK_PLAYBACK=false to turn off. */
const MOCK_PLAYBACK_FLAG = import.meta.env.VITE_MOCK_PLAYBACK;
const MOCK_PLAYBACK_ENABLED =
  MOCK_PLAYBACK_FLAG === "false" || MOCK_PLAYBACK_FLAG === "0"
    ? false
    : MOCK_PLAYBACK_FLAG === "true" ||
    (import.meta.env.DEV &&
      (CALL_WS_URL.includes("localhost:8001") || CALL_WS_URL.includes("127.0.0.1:8001")));
const SPEAKER_BY_PROFESSOR_ID: Record<string, "alaa" | "hammad" | "hanan" | "khalil"> = {
  geddo: "alaa",
  hammad: "hammad",
  hanan: "hanan",
  mk: "khalil"
};

function App() {
  const [isCallModalOpen, setIsCallModalOpen] = useState(false);
  const [selectedProfessor, setSelectedProfessor] = useState<{ id: string; name: string } | null>(null);
  const [callStatus, setCallStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [callError, setCallError] = useState("");
  const [callAudioHint, setCallAudioHint] = useState("");
  const [userVoiceLevel, setUserVoiceLevel] = useState(0);
  const [isProfessorTalking, setIsProfessorTalking] = useState(false);
  const isProfessorTalkingRef = useRef(false);
  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const captureScriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const callMixerRef = useRef<MediaStreamAudioDestinationNode | null>(null);
  const callRecorderRef = useRef<MediaRecorder | null>(null);
  const callRecordedChunksRef = useRef<Blob[]>([]);
  const captureSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const captureSilentGainRef = useRef<GainNode | null>(null);
  const utteranceBufferRef = useRef<UtteranceBuffer>(createUtteranceBuffer());
  const inUtteranceRef = useRef(false);
  const lastVoiceAtRef = useRef(0);
  const silenceStartedAtRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioDecoderRef = useRef<AudioDecoder | null>(null);
  const playbackCursorRef = useRef(0);
  const nextPacketTimestampUsRef = useRef(0);
  const playbackSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  /** After barge-in: drop server opus until this response ends (`complete`). */
  const ignoreProfessorAudioRef = useRef(false);
  /** Set to true when server sends `complete` — used to stop talking state once all queued audio has played out. */
  const responseCompleteRef = useRef(false);
  const waveformDecayIntervalRef = useRef<number | null>(null);
  const mockProfessorAudioRef = useRef<HTMLAudioElement | null>(null);

  const stopMockProfessorPlayback = () => {
    const a = mockProfessorAudioRef.current;
    if (a) {
      a.pause();
      mockProfessorAudioRef.current = null;
    }
  };

  const setProfessorTalking = (value: boolean) => {
    isProfessorTalkingRef.current = value;
    setIsProfessorTalking(value);
  };

  const stopPlaybackSources = () => {
    for (const src of playbackSourcesRef.current) {
      try {
        src.stop(0);
      } catch {
        /* already stopped */
      }
    }
    playbackSourcesRef.current = [];
    playbackCursorRef.current = 0;
    responseCompleteRef.current = false;
  };

  const interruptProfessorTurn = (audioSamples?: Float32Array, sampleRate?: number) => {
    stopMockProfessorPlayback();
    stopPlaybackSources();
    if (audioDecoderRef.current && audioDecoderRef.current.state !== "closed") {
      audioDecoderRef.current.close();
    }
    audioDecoderRef.current = null;
    nextPacketTimestampUsRef.current = 0;
    setProfessorTalking(false);
    ignoreProfessorAudioRef.current = true;

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (audioSamples && sampleRate) {
        const wav = encodeWavPcm16Mono(audioSamples, sampleRate);
        const data = arrayBufferToBase64(wav);
        ws.send(JSON.stringify({ type: "interrupt", data, format: "wav" }));
      } else {
        ws.send(JSON.stringify({ type: "interrupt" }));
      }
    }

    resetUtteranceBuffer(utteranceBufferRef.current);
    inUtteranceRef.current = false;
    silenceStartedAtRef.current = null;
  };

  const playMockProfessorClip = (src: string) => {
    stopMockProfessorPlayback();
    const audio = new Audio(src);
    mockProfessorAudioRef.current = audio;
    audio.onplay = () => {
      setProfessorTalking(true);
    };
    audio.onended = () => {
      setProfessorTalking(false);
      mockProfessorAudioRef.current = null;
    };
    audio.onerror = () => {
      setProfessorTalking(false);
      mockProfessorAudioRef.current = null;
    };
    void audio.play().catch(() => {
      setProfessorTalking(false);
      mockProfessorAudioRef.current = null;
    });
  };

  const handleOpenCallModal = (professorId: string, professorName: string) => {
    setSelectedProfessor({ id: professorId, name: professorName });
    setCallStatus("idle");
    setCallError("");
    setCallAudioHint("");
    ignoreProfessorAudioRef.current = false;
    setProfessorTalking(false);
    setIsCallModalOpen(true);
  };

  const stopCallCapture = () => {
    if (captureScriptProcessorRef.current) {
      captureScriptProcessorRef.current.disconnect();
      captureScriptProcessorRef.current.onaudioprocess = null;
      captureScriptProcessorRef.current = null;
    }
    if (captureSourceRef.current) {
      captureSourceRef.current.disconnect();
      captureSourceRef.current = null;
    }
    if (captureSilentGainRef.current) {
      captureSilentGainRef.current.disconnect();
      captureSilentGainRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    resetUtteranceBuffer(utteranceBufferRef.current);
    inUtteranceRef.current = false;
    lastVoiceAtRef.current = 0;
    silenceStartedAtRef.current = null;
    setUserVoiceLevel(0);
    setCallAudioHint("");
  };

  const sendWavChunk = (samples: Float32Array, sampleRate: number) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const wav = encodeWavPcm16Mono(samples, sampleRate);
    const data = arrayBufferToBase64(wav);
    ws.send(JSON.stringify({ type: "audio_chunk", data, format: "wav" }));
  };

  const flushEndOfUtterance = (sampleRate: number) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    const chunkSamples = Math.max(
      1,
      Math.floor((sampleRate * CALL_AUDIO_CONFIG.CHUNK_DURATION_MS) / 1000)
    );
    const buf = utteranceBufferRef.current;

    while (buf.totalSamples >= chunkSamples) {
      const slice = utteranceTake(buf, chunkSamples);
      if (slice) sendWavChunk(slice, sampleRate);
    }
    const tail = utteranceDrainAll(buf);
    if (tail && tail.length > 0) {
      sendWavChunk(tail, sampleRate);
    }
    ws.send(JSON.stringify({ type: "audio_end" }));
    inUtteranceRef.current = false;
    silenceStartedAtRef.current = null;
    setCallAudioHint("Waiting for the professor's response... speak again when you are ready.");
  };

  const startContinuousCapture = async () => {
    stopCallCapture();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      mediaStreamRef.current = stream;

      const ctx = audioContextRef.current;
      if (!ctx) {
        setCallStatus("error");
        setCallError("Audio context not initialized.");
        return;
      }
      const sampleRate = ctx.sampleRate;
      const chunkSamples = Math.max(
        1,
        Math.floor((sampleRate * CALL_AUDIO_CONFIG.CHUNK_DURATION_MS) / 1000)
      );

      const source = ctx.createMediaStreamSource(stream);
      captureSourceRef.current = source;
      
      if (callMixerRef.current) {
        source.connect(callMixerRef.current);
      }

      const processor = ctx.createScriptProcessor(CALL_AUDIO_CONFIG.SCRIPT_BUFFER_SIZE, 2, 2);
      captureScriptProcessorRef.current = processor;
      const silentGain = ctx.createGain();
      silentGain.gain.value = 0;
      captureSilentGainRef.current = silentGain;

      source.connect(processor);
      processor.connect(silentGain);
      silentGain.connect(ctx.destination);

      if (ctx.state === "suspended") {
        await ctx.resume();
      }

      resetUtteranceBuffer(utteranceBufferRef.current);
      inUtteranceRef.current = false;
      lastVoiceAtRef.current = performance.now();
      silenceStartedAtRef.current = null;
      setCallAudioHint("Call is live. Speak naturally.");

      processor.onaudioprocess = (event: AudioProcessingEvent) => {
        for (let c = 0; c < event.outputBuffer.numberOfChannels; c += 1) {
          event.outputBuffer.getChannelData(c).fill(0);
        }
        const mono = downmixToMono(event.inputBuffer);
        const energy = rmsFloat32(mono);
        const now = performance.now();
        const isSpeech = energy >= CALL_AUDIO_CONFIG.VAD_ENERGY_THRESHOLD;
        setUserVoiceLevel(Math.min(1, Math.max(0, energy * 18)));
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        if (isSpeech && isProfessorTalkingRef.current) {
          const existing = utteranceDrainAll(utteranceBufferRef.current);
          const allSamples = new Float32Array((existing ? existing.length : 0) + mono.length);
          if (existing) {
            allSamples.set(existing, 0);
            allSamples.set(mono, existing.length);
          } else {
            allSamples.set(mono, 0);
          }
          
          interruptProfessorTurn(allSamples, sampleRate);
          
          lastVoiceAtRef.current = now;
          silenceStartedAtRef.current = null;
          inUtteranceRef.current = true;
          setCallAudioHint("Listening...");
          return;
        }

        if (isSpeech) {
          lastVoiceAtRef.current = now;
          silenceStartedAtRef.current = null;
          if (!inUtteranceRef.current) {
            inUtteranceRef.current = true;
            setCallAudioHint("Listening...");
          }
          utteranceAppend(utteranceBufferRef.current, mono);

          while (utteranceBufferRef.current.totalSamples >= chunkSamples) {
            const slice = utteranceTake(utteranceBufferRef.current, chunkSamples);
            if (slice) sendWavChunk(slice, sampleRate);
          }
          return;
        }

        if (!inUtteranceRef.current) {
          return;
        }

        utteranceAppend(utteranceBufferRef.current, mono);
        if (silenceStartedAtRef.current === null) {
          silenceStartedAtRef.current = now;
        }
        if (now - silenceStartedAtRef.current >= CALL_AUDIO_CONFIG.VAD_SILENCE_MS) {
          flushEndOfUtterance(sampleRate);
        }
      };
    } catch {
      setCallStatus("error");
      setCallError("Cannot access the microphone. Please allow mic permission and try again.");
    }
  };

  const resetPlaybackState = () => {
    playbackCursorRef.current = 0;
    nextPacketTimestampUsRef.current = 0;
  };

  const closePlaybackPipeline = () => {
    stopPlaybackSources();
    ignoreProfessorAudioRef.current = false;
    if (audioDecoderRef.current && audioDecoderRef.current.state !== "closed") {
      audioDecoderRef.current.close();
    }
    audioDecoderRef.current = null;
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => undefined);
    }
    audioContextRef.current = null;
    setProfessorTalking(false);
    resetPlaybackState();
  };

  const handleDecodedAudio = (audioData: AudioData) => {
    const audioContext = audioContextRef.current;
    if (!audioContext) {
      audioData.close();
      return;
    }

    if (audioContext.state === "suspended") {
      audioContext.resume().catch(() => undefined);
    }

    const audioBuffer = audioContext.createBuffer(
      audioData.numberOfChannels,
      audioData.numberOfFrames,
      audioData.sampleRate
    );

    for (let channel = 0; channel < audioData.numberOfChannels; channel += 1) {
      const channelData = new Float32Array(audioData.numberOfFrames);
      audioData.copyTo(channelData, { planeIndex: channel });
      audioBuffer.copyToChannel(channelData, channel);
    }

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    if (callMixerRef.current) {
      source.connect(callMixerRef.current);
    }
    playbackSourcesRef.current.push(source);
    source.addEventListener("ended", () => {
      playbackSourcesRef.current = playbackSourcesRef.current.filter((node) => node !== source);
      // If the server already sent "complete" and this was the last queued buffer, stop the talking indicator.
      if (responseCompleteRef.current && playbackSourcesRef.current.length === 0) {
        responseCompleteRef.current = false;
        setProfessorTalking(false);
      }
    });

    const startAt = Math.max(audioContext.currentTime + 0.02, playbackCursorRef.current);
    source.start(startAt);
    playbackCursorRef.current = startAt + audioBuffer.duration;
    audioData.close();
  };

  const ensurePlaybackDecoder = (): boolean => {
    if (typeof AudioDecoder === "undefined") {
      return false;
    }
    try {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 48000 });
      }
      void audioContextRef.current.resume();
      if (!audioDecoderRef.current || audioDecoderRef.current.state === "closed") {
        audioDecoderRef.current = new AudioDecoder({
          output: handleDecodedAudio,
          error: () => {
            setCallStatus("error");
            setCallError("A temporary issue occurred while playing the voice response.");
          }
        });
        audioDecoderRef.current.configure({
          codec: "opus",
          sampleRate: 48000,
          numberOfChannels: 1
        });
      }
      return audioDecoderRef.current.state === "configured";
    } catch {
      return false;
    }
  };

  const initializePlaybackPipeline = async (): Promise<boolean> => {
    if (typeof AudioDecoder === "undefined") {
      setCallAudioHint("Connected.");
      return false;
    }

    try {
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 48000 });
      }
      if (audioContextRef.current.state === "suspended") {
        await audioContextRef.current.resume();
      }

      if (!audioDecoderRef.current || audioDecoderRef.current.state === "closed") {
        audioDecoderRef.current = new AudioDecoder({
          output: handleDecodedAudio,
          error: () => {
            setCallStatus("error");
            setCallError("A temporary issue occurred while playing the voice response.");
          }
        });
        audioDecoderRef.current.configure({
          codec: "opus",
          sampleRate: 48000,
          numberOfChannels: 1
        });
      }

      resetPlaybackState();
      return true;
    } catch {
      return false;
    }
  };

  const decodeIncomingOpusPacket = (buffer: ArrayBuffer) => {
    if (ignoreProfessorAudioRef.current) {
      return;
    }
    if (!ensurePlaybackDecoder()) {
      return;
    }

    try {
      const chunk = new EncodedAudioChunk({
        type: "key",
        timestamp: nextPacketTimestampUsRef.current,
        duration: 20_000,
        data: new Uint8Array(buffer)
      });
      console.log("decoded incoming audio");
      nextPacketTimestampUsRef.current += 20_000;
      audioDecoderRef.current?.decode(chunk);
    } catch {
      setCallStatus("error");
      setCallError("A temporary issue occurred while receiving audio.");
    }
  };

  const closeCurrentSocket = (sendTerminate: boolean) => {
    if (!wsRef.current) return;
    if (sendTerminate && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "terminate" }));
    }
    wsRef.current.close();
    wsRef.current = null;
  };

  const handleCloseCallModal = () => {
    if (callRecorderRef.current && callRecorderRef.current.state !== "inactive") {
      callRecorderRef.current.onstop = () => {
        callRecordedChunksRef.current = [];
      };
      callRecorderRef.current.stop();
    } else {
      callRecordedChunksRef.current = [];
    }
    callRecorderRef.current = null;
    if (callMixerRef.current) {
      callMixerRef.current.disconnect();
      callMixerRef.current = null;
    }

    stopMockProfessorPlayback();
    stopCallCapture();
    closeCurrentSocket(true);
    closePlaybackPipeline();
    setIsCallModalOpen(false);
    setSelectedProfessor(null);
    setCallStatus("idle");
    setCallError("");
    setCallAudioHint("");
  };

  const handleStartCall = () => {
    if (!selectedProfessor) return;

    const speaker = SPEAKER_BY_PROFESSOR_ID[selectedProfessor.id];
    if (!speaker) {
      setCallStatus("error");
      setCallError("Unable to start the call. Please try again.");
      return;
    }

    closeCurrentSocket(true);
    stopMockProfessorPlayback();
    closePlaybackPipeline();
    setCallStatus("connecting");
    setCallError("");

    void (async () => {
      await initializePlaybackPipeline();

      const ws = new WebSocket(CALL_WS_URL);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "init", speaker }));
        setCallStatus("connected");

        if (audioContextRef.current) {
          if (!callMixerRef.current) {
            callMixerRef.current = audioContextRef.current.createMediaStreamDestination();
          }
          const stream = callMixerRef.current.stream;
          let mimeType = "audio/webm";
          if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = "audio/mp4";
          }
          const recorder = new MediaRecorder(stream, { mimeType });
          callRecorderRef.current = recorder;
          callRecordedChunksRef.current = [];
          recorder.ondataavailable = (e) => {
            if (e.data.size > 0) callRecordedChunksRef.current.push(e.data);
          };
          recorder.start(1000);
        }

        setCallAudioHint("Call is live. Speak naturally.");
        void startContinuousCapture();
      };

      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          try {
            const data = JSON.parse(event.data) as { type?: string; error?: string };
            if (data.type === "complete") {
              ignoreProfessorAudioRef.current = false;
              setCallAudioHint("Your turn again. Speak whenever you are ready.");
              if (MOCK_PLAYBACK_ENABLED) {
                const envUrl = (import.meta.env.VITE_MOCK_PLAYBACK_URL as string | undefined)?.trim();
                const clip =
                  envUrl ||
                  PROFESSORS.find((p) => p.id === selectedProfessor?.id)?.audioSrc ||
                  "/audio/geddo.wav";
                playMockProfessorClip(clip);
              } else {
                // Don't clear the talking state immediately — wait until the last queued
                // AudioBufferSourceNode fires its "ended" event. If there's nothing buffered
                // (e.g. the response was empty or all audio was already consumed), clear now.
                if (playbackSourcesRef.current.length === 0) {
                  setProfessorTalking(false);
                } else {
                  responseCompleteRef.current = true;
                }
              }
              return;
            }
            if (data.type === "error") {
              setCallStatus("error");
              setCallError(data.error || "A server error occurred during the call.");
              return;
            }
          } catch {
          }
          return;
        }

        if (event.data instanceof ArrayBuffer) {
          if (ignoreProfessorAudioRef.current) {
            return;
          }
          setProfessorTalking(true);
          decodeIncomingOpusPacket(event.data);
          return;
        }

        if (event.data instanceof Blob) {
          void event.data.arrayBuffer().then((buffer) => {
            if (ignoreProfessorAudioRef.current) {
              return;
            }
            setProfessorTalking(true);
            decodeIncomingOpusPacket(buffer);
          });
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        stopMockProfessorPlayback();
        setCallStatus("error");
        setCallError("Cannot start the call right now. Please try again shortly.");
        setProfessorTalking(false);
      };

      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        stopMockProfessorPlayback();
        stopCallCapture();
        closePlaybackPipeline();
        setCallStatus((prev) => (prev === "error" ? prev : "idle"));
      };
    })();
  };

  useEffect(() => {
    waveformDecayIntervalRef.current = window.setInterval(() => {
      setUserVoiceLevel((prev) => (prev > 0.02 ? prev * 0.75 : 0));
    }, 80);
    return () => {
      if (waveformDecayIntervalRef.current !== null) {
        window.clearInterval(waveformDecayIntervalRef.current);
        waveformDecayIntervalRef.current = null;
      }
      stopMockProfessorPlayback();
      stopCallCapture();
      closeCurrentSocket(true);
      closePlaybackPipeline();
    };
  }, []);

  const callButtonText = callStatus === "connecting"
    ? "Connecting..."
    : callStatus === "connected"
      ? "Reconnect"
      : "Start Call";

  return (
    <div dir="ltr" lang="en" className="relative min-h-screen bg-slate-50 text-slate-900 pb-24 overflow-hidden selection:bg-teal-100 selection:text-teal-900 font-sans">
      <div className="absolute inset-0 z-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:radial-gradient(ellipse_80%_100%_at_50%_0%,#000_70%,transparent_100%)]"></div>

      <div className="absolute z-0 top-[-10%] left-[-10%] w-[40%] h-[40%] bg-emerald-300/40 rounded-full mix-blend-multiply blur-[120px] pointer-events-none"></div>
      <div className="absolute z-0 top-[10%] right-[-5%] w-[35%] h-[35%] bg-teal-300/40 rounded-full mix-blend-multiply blur-[120px] pointer-events-none"></div>
      <div className="absolute z-0 bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-cyan-300/30 rounded-full mix-blend-multiply blur-[120px] pointer-events-none"></div>

      <div className="relative z-10">
        <header className="pt-24 pb-16 px-4 md:px-8 text-center space-y-6">
          <div className="max-w-4xl mx-auto space-y-6 cursor-default">
            <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight text-slate-900 pb-2 cursor-default">
              Ask the <span className="bg-clip-text text-transparent bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500">Digital Twins</span>
            </h1>
            <p className="text-xl md:text-2xl text-slate-600 font-medium max-w-2xl mx-auto leading-relaxed cursor-default">
              Interact with Ain Shams University virtual professors and get fast, accurate answers in each professor's unique style.
            </p>
          </div>
        </header>

        <main className="max-w-6xl mx-auto px-4 md:px-8 mt-4 space-y-32">
          <section className="relative">
            <div className="mb-12 text-center">
              <h2 className="text-3xl md:text-4xl font-bold mb-4 text-slate-800">Virtual Professors</h2>
              <p className="text-lg text-slate-500 font-medium">Choose the right professor and hear a sample answer before starting your call.</p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 gap-8">
              {PROFESSORS.map((prof) => (
                <ProfessorCard
                  key={prof.id}
                  id={prof.id}
                  name={prof.name}
                  description={prof.description}
                  audioSrc={prof.audioSrc}
                  avatarInitials={prof.initials}
                  avatarSrc={prof.avatarSrc}
                  onStartCall={handleOpenCallModal}
                />
              ))}
            </div>
          </section>
        </main>
      </div>

      {isCallModalOpen && selectedProfessor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 px-4">
          <div className="w-full max-w-md rounded-3xl border border-white/50 bg-white/90 backdrop-blur-xl shadow-2xl p-6 space-y-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-2xl font-bold text-slate-900">Call with {selectedProfessor.name}</h3>
                {/* <p className="text-slate-600 mt-1">WebSocket call session is active.</p> */}
              </div>
              <Button type="button" variant="ghost" size="icon" className="rounded-full" onClick={handleCloseCallModal}>
                <X className="h-5 w-5" />
              </Button>
            </div>

            <div className="rounded-2xl bg-slate-100 p-4 text-sm text-slate-700 space-y-1">
              {callStatus === "idle" && <p>Press Start Call to connect.</p>}
              {callStatus === "connecting" && <p>Connecting to server...</p>}
              {callStatus === "connected" && <p>Call is live. Speak naturally.</p>}
              {callStatus === "error" && <p>{callError}</p>}
              {callAudioHint && <p className="text-slate-600 text-xs mt-1">{callAudioHint}</p>}
            </div>

            <div className="rounded-2xl bg-slate-100/80 border border-white/70 p-4 space-y-4">
              <div className="flex justify-center">
                <div className="relative h-24 w-24">
                  <span
                    className={`absolute inset-0 rounded-full transition-all duration-300 ${isProfessorTalking
                      ? "bg-emerald-400/25 scale-125 animate-ping"
                      : "bg-slate-300/25 scale-100"
                      }`}
                  />
                  <span
                    className={`absolute inset-2 rounded-full transition-all duration-300 ${isProfessorTalking
                      ? "bg-emerald-300/40 scale-115 animate-pulse"
                      : "bg-slate-300/30"
                      }`}
                  />
                  <div
                    className={`absolute inset-[14px] rounded-full transition-all duration-300 ${isProfessorTalking
                      ? "bg-emerald-400 shadow-[0_0_35px_rgba(16,185,129,0.8)] scale-110 animate-pulse"
                      : "bg-slate-300 shadow-inner animate-pulse"
                      }`}
                  />
                </div>
              </div>
              <div className="h-12 flex items-center justify-center gap-[3px]">
                {Array.from({ length: 28 }, (_, index) => {
                  const offset = Math.abs(index - 13.5);
                  const waveFactor = Math.max(0.25, 1 - offset / 13.5);
                  const dynamic = Math.max(0.12, userVoiceLevel * waveFactor);
                  const height = 10 + dynamic * 30;
                  return (
                    <span
                      key={`voice-wave-${index}`}
                      className="w-[4px] rounded-full bg-emerald-500/85 transition-all duration-75"
                      style={{ height: `${height}px`, opacity: 0.25 + dynamic * 0.75 }}
                    />
                  );
                })}
              </div>
            </div>

            <div className="flex gap-3">
              <Button
                type="button"
                className="flex-1 h-11 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700"
                onClick={handleStartCall}
                disabled={callStatus === "connecting"}
              >
                {callStatus === "connecting" ? (
                  <>
                    <Loader2 className="h-4 w-4 ml-2 animate-spin" />
                    {callButtonText}
                  </>
                ) : (
                  <>
                    <PhoneCall className="h-4 w-4 ml-2" />
                    {callButtonText}
                  </>
                )}
              </Button>
              <Button type="button" variant="outline" className="h-11 rounded-xl" onClick={handleCloseCallModal}>
                End
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;