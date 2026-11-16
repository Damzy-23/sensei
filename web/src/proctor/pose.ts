// Head pose from the face detector's transformation matrix: is the face roughly towards the
// screen? Pure arithmetic, tested in pose.test.mjs.
//
// This is head direction, not gaze: it cannot tell which part of the screen is being read,
// so the limits are generous. Someone reading the bottom of the page or glancing at their
// keys is inside them; someone turned to a second monitor or to another person is not.
//
// The angles are measured from the camera, not from the screen. A laptop camera sits well
// below eye level and looks up, so a level head already reads as tipped up by about 25
// degrees, and a head bent over the keys reads as only a little down. That is why the
// up-down limit is the wider of the two: 30 would sit a few degrees from a candidate who is
// looking straight at their own screen.

export const YAW_LIMIT_DEG = 35;
export const PITCH_LIMIT_DEG = 40;

const DEGREES = 180 / Math.PI;

/** Left-right (yaw) and up-down (pitch) turn of the head, in degrees. 0 and 0 is straight at
 *  the camera. `matrix` is the 4x4 facial transformation matrix as MediaPipe returns it:
 *  16 numbers, column by column. Its third column is where the nose points, in camera space,
 *  and the camera sits along +z. Returns null for anything that is not such a matrix. */
export function headAngles(matrix: ArrayLike<number> | null | undefined): { yaw: number; pitch: number } | null {
  if (!matrix || matrix.length !== 16) return null;
  const x = matrix[8], y = matrix[9], z = matrix[10];
  const length = Math.hypot(x, y, z);
  if (!Number.isFinite(length) || length === 0) return null;
  return { yaw: Math.atan2(x, z) * DEGREES, pitch: Math.atan2(y, Math.hypot(x, z)) * DEGREES };
}

/** True when the head is turned no further than the limits. An unreadable matrix is not facing. */
export function facingScreen(matrix: ArrayLike<number> | null | undefined): boolean {
  const angles = headAngles(matrix);
  return angles !== null && Math.abs(angles.yaw) <= YAW_LIMIT_DEG && Math.abs(angles.pitch) <= PITCH_LIMIT_DEG;
}
