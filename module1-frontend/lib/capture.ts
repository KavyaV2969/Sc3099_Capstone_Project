export type ChallengeType = "blink" | "head_turn";

// Rates from your testing: 8 fps x 3 s = 24 frames, 5 fps x 5 s = 25 frames
export const CHALLENGE_CONFIG: Record<ChallengeType, { fps: number; seconds: number; prompt: string }> = {
  blink: { fps: 8, seconds: 3, prompt: "Look at the camera, blink once, then keep your eyes open" },
  head_turn: { fps: 5, seconds: 5, prompt: "Turn your head to one side, as far as is comfortable" },
};

const MAX_FRAMES = 30; // the backend's limit

export async function captureClip(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  fps: number,
  seconds: number,
  onProgress?: (done: number, total: number) => void
): Promise<string[]> {
  const total = Math.min(Math.round(fps * seconds), MAX_FRAMES);
  const interval = 1000 / fps;
  const w = Math.min(800, video.videoWidth);
  const h = Math.round((video.videoHeight * w) / video.videoWidth);
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas unavailable");

  const frames: string[] = [];
  const start = performance.now();
  for (let i = 0; i < total; i++) {
    // wait until this frame's slot, so timing doesn't drift
    const wait = start + i * interval - performance.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    ctx.drawImage(video, 0, 0, w, h);
    frames.push(canvas.toDataURL("image/jpeg", 0.75));
    onProgress?.(i + 1, total);
  }
  return frames;
}