// Head pose arithmetic, checked with rotation matrices built here. Run: npm test

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { loadTs } from "./load-ts.mjs";

const { headAngles, facingScreen, YAW_LIMIT_DEG, PITCH_LIMIT_DEG } = await loadTs(new URL("./pose.ts", import.meta.url));

const rad = (deg) => (deg * Math.PI) / 180;

/** A column-major 4x4 matrix for a head turned `yaw` degrees sideways and tipped `pitch` degrees, 60 cm from the camera. */
function head(yaw, pitch, scale = 1) {
  const cy = Math.cos(rad(yaw)), sy = Math.sin(rad(yaw)), cp = Math.cos(rad(pitch)), sp = Math.sin(rad(pitch));
  // The columns are where the head's own x, y and z axes point. z is the nose.
  const x = [cy, 0, -sy];
  const y = [-sy * sp, cp, -cy * sp];
  const z = [sy * cp, sp, cy * cp];
  return [...x, 0, ...y, 0, ...z, 0].map((v) => v * scale).concat([0, 0, -60, 1]);
}

const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-6, `${actual} is not ${expected}`);

test("a head straight at the camera has no yaw and no pitch", () => {
  const angles = headAngles(head(0, 0));
  close(angles.yaw, 0);
  close(angles.pitch, 0);
  assert.equal(facingScreen(head(0, 0)), true);
});

test("yaw and pitch are read back in degrees", () => {
  for (const [yaw, pitch] of [[20, 0], [-40, 0], [0, 15], [0, -25], [30, 10], [-10, -20]]) {
    const angles = headAngles(head(yaw, pitch));
    close(angles.yaw, yaw);
    close(angles.pitch, pitch);
  }
});

test("the matrix may carry a scale", () => {
  const angles = headAngles(head(25, -10, 7.5));
  close(angles.yaw, 25);
  close(angles.pitch, -10);
});

test("small turns are still facing the screen; large ones are not", () => {
  assert.equal(facingScreen(head(YAW_LIMIT_DEG - 1, 0)), true);
  assert.equal(facingScreen(head(-(YAW_LIMIT_DEG - 1), 0)), true);
  assert.equal(facingScreen(head(YAW_LIMIT_DEG + 1, 0)), false);
  assert.equal(facingScreen(head(-(YAW_LIMIT_DEG + 1), 0)), false);
  assert.equal(facingScreen(head(0, PITCH_LIMIT_DEG - 1)), true);
  assert.equal(facingScreen(head(0, -(PITCH_LIMIT_DEG - 1))), true);
  assert.equal(facingScreen(head(0, PITCH_LIMIT_DEG + 1)), false);
  assert.equal(facingScreen(head(0, -(PITCH_LIMIT_DEG + 1))), false);
  assert.equal(facingScreen(head(90, 0)), false);
  assert.equal(facingScreen(head(170, 0)), false, "the back of a head is not facing the screen");
});

test("anything that is not a 4x4 matrix is not facing", () => {
  for (const bad of [null, undefined, [], [1, 0, 0, 0], new Array(16).fill(0), new Array(16).fill(NaN)]) {
    assert.equal(headAngles(bad), null);
    assert.equal(facingScreen(bad), false);
  }
});

test("the detector loads the WASM build that matches the installed package", () => {
  // The JS comes from node_modules and the WASM from a CDN: a mismatch only fails in the browser.
  const pinned = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).dependencies["@mediapipe/tasks-vision"];
  const used = /MEDIAPIPE_VERSION = "([^"]+)"/.exec(readFileSync(new URL("./detector.ts", import.meta.url), "utf8"))?.[1];
  assert.match(pinned, /^\d+\.\d+\.\d+$/, "the package must be pinned to an exact version");
  assert.equal(used, pinned);
});
