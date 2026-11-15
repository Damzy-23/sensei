// The detectors behind the proctor: MediaPipe's face and hand landmarkers, run in this
// browser on frames of the camera preview. Nothing here makes a request with a frame in it.
//
// The library is loaded only when the proctor is turned on (a dynamic import, so it is not
// in the main bundle). Its WASM runtime and the two model files are downloaded from the
// library's CDN and Google's public model bucket; those requests fetch files and send nothing.
// The package is pinned to the 0.10 line on purpose: the 1.x releases say in their README that
// they send usage metrics to Google, which would break the promise that only reminders leave
// the browser. Read that README again before moving the pin.

import type { FaceLandmarker, HandLandmarker } from "@mediapipe/tasks-vision";
import { facingScreen } from "./pose";

/** Must equal the version pinned in package.json: the WASM has to match the JS (pose.test.mjs checks). */
export const MEDIAPIPE_VERSION = "0.10.35";
const WASM_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/wasm`;
const MODELS = "https://storage.googleapis.com/mediapipe-models";
const FACE_MODEL = `${MODELS}/face_landmarker/face_landmarker/float16/1/face_landmarker.task`;
const HAND_MODEL = `${MODELS}/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task`;

export interface Detector {
  /** Is there a face in this frame, roughly towards the screen? */
  facing(video: HTMLVideoElement, timestampMs: number): boolean;
  /** How many hands are in this frame: 0, 1 or 2. */
  hands(video: HTMLVideoElement, timestampMs: number): number;
  /** Release both models. The detector must not be used afterwards. */
  close(): void;
}

/** Download and start both detectors. Rejects if the library, the runtime or a model cannot be loaded. */
export async function loadDetector(): Promise<Detector> {
  const { FilesetResolver, FaceLandmarker, HandLandmarker } = await import("@mediapipe/tasks-vision");
  const files = await FilesetResolver.forVisionTasks(WASM_URL);
  // CPU on purpose: it behaves the same in every browser, and one frame takes a few milliseconds.
  const [face, hand] = await Promise.allSettled([
    FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: FACE_MODEL, delegate: "CPU" },
      runningMode: "VIDEO", numFaces: 1, outputFacialTransformationMatrixes: true,
    }),
    HandLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: HAND_MODEL, delegate: "CPU" },
      runningMode: "VIDEO", numHands: 2,
    }),
  ]);
  if (face.status === "rejected" || hand.status === "rejected") {
    // One may have loaded while the other failed: do not leave it running.
    if (face.status === "fulfilled") face.value.close();
    if (hand.status === "fulfilled") hand.value.close();
    throw face.status === "rejected" ? face.reason : (hand as PromiseRejectedResult).reason;
  }
  const faces: FaceLandmarker = face.value;
  const handsModel: HandLandmarker = hand.value;
  return {
    facing: (video, timestampMs) => {
      const result = faces.detectForVideo(video, timestampMs);
      return result.faceLandmarks.length > 0 && facingScreen(result.facialTransformationMatrixes[0]?.data);
    },
    hands: (video, timestampMs) => Math.min(2, handsModel.detectForVideo(video, timestampMs).landmarks.length),
    close: () => { faces.close(); handsModel.close(); },
  };
}
