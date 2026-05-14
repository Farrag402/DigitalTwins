/**
 * Tunables for call-style capture: fixed-duration chunks + VAD end-of-turn.
 * Adjust CHUNK_DURATION_MS / VAD_* without touching UI code.
 */
export const CALL_AUDIO_CONFIG = {
  /** Length of each audio_chunk while the user is speaking (ms). */
  CHUNK_DURATION_MS: 2000,
  /** How long energy must stay below threshold to end the turn (ms). */
  VAD_SILENCE_MS: 700,
  /** RMS on mono float32 [-1, 1]; increase in noisy rooms. */
  VAD_ENERGY_THRESHOLD: 0.012,
  /** ScriptProcessor buffer size (256–16384, power of 2). */
  SCRIPT_BUFFER_SIZE: 4096
} as const;

export function downmixToMono(inputBuffer: AudioBuffer): Float32Array {
  const n = inputBuffer.length;
  const ch0 = inputBuffer.getChannelData(0);
  if (inputBuffer.numberOfChannels === 1) {
    return new Float32Array(ch0);
  }
  const ch1 = inputBuffer.getChannelData(1);
  const mono = new Float32Array(n);
  for (let i = 0; i < n; i += 1) {
    mono[i] = (ch0[i] + ch1[i]) * 0.5;
  }
  return mono;
}

export function rmsFloat32(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const x = samples[i];
    sum += x * x;
  }
  return Math.sqrt(sum / samples.length);
}

/** 16-bit mono PCM WAV */
export function encodeWavPcm16Mono(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const numChannels = 1;
  const bitsPerSample = 16;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeStr = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i += 1) {
      view.setUint8(offset + i, s.charCodeAt(i));
    }
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    const v = s < 0 ? s * 0x8000 : s * 0x7fff;
    view.setInt16(offset, v, true);
    offset += 2;
  }
  return buffer;
}

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const sub = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...sub);
  }
  return btoa(binary);
}

export type UtteranceBuffer = {
  chunks: Float32Array[];
  totalSamples: number;
};

export function createUtteranceBuffer(): UtteranceBuffer {
  return { chunks: [], totalSamples: 0 };
}

export function utteranceAppend(state: UtteranceBuffer, data: Float32Array): void {
  state.chunks.push(data);
  state.totalSamples += data.length;
}

/** Take exactly `count` samples from the front; returns null if not enough. */
export function utteranceTake(state: UtteranceBuffer, count: number): Float32Array | null {
  if (state.totalSamples < count) return null;
  const out = new Float32Array(count);
  let written = 0;
  while (written < count) {
    const first = state.chunks[0];
    const need = count - written;
    if (first.length <= need) {
      out.set(first, written);
      written += first.length;
      state.chunks.shift();
    } else {
      out.set(first.subarray(0, need), written);
      state.chunks[0] = first.subarray(need);
      written += need;
    }
  }
  state.totalSamples -= count;
  return out;
}

/** Drain all remaining samples into one buffer. */
export function utteranceDrainAll(state: UtteranceBuffer): Float32Array | null {
  if (state.totalSamples === 0) return null;
  const out = new Float32Array(state.totalSamples);
  let written = 0;
  for (const c of state.chunks) {
    out.set(c, written);
    written += c.length;
  }
  state.chunks = [];
  state.totalSamples = 0;
  return out;
}

export function resetUtteranceBuffer(state: UtteranceBuffer): void {
  state.chunks = [];
  state.totalSamples = 0;
}
