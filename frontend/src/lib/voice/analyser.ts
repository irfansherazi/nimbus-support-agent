// Audio level meters for the two waveforms (mic and agent), via Web Audio AnalyserNodes.

export interface LevelMeter {
  /** Current loudness, 0..1. */
  level: () => number;
  /** Frequency-domain magnitudes 0..1 for drawing bars. */
  bars: (count: number) => number[];
  close: () => void;
}

export function createLevelMeter(ctx: AudioContext, stream: MediaStream): LevelMeter {
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.7;
  source.connect(analyser);
  const time = new Uint8Array(analyser.fftSize);
  const freq = new Uint8Array(analyser.frequencyBinCount);

  return {
    level() {
      analyser.getByteTimeDomainData(time);
      let sum = 0;
      for (const v of time) sum += ((v - 128) / 128) ** 2;
      return Math.min(1, Math.sqrt(sum / time.length) * 3);
    },
    bars(count) {
      analyser.getByteFrequencyData(freq);
      const usable = Math.floor(freq.length * 0.6); // speech lives in the lower bins
      const step = Math.max(1, Math.floor(usable / count));
      return Array.from({ length: count }, (_, i) => {
        let max = 0;
        for (let j = i * step; j < (i + 1) * step && j < usable; j++) max = Math.max(max, freq[j]);
        return max / 255;
      });
    },
    close() {
      source.disconnect();
      analyser.disconnect();
    },
  };
}
