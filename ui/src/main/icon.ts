// The tray icon, drawn in code so the mode is visible at a glance without shipping image files.

import { nativeImage, type NativeImage } from 'electron';

import type { ModeId } from '../shared/types';

const COLORS: Record<ModeId | 'offline', [number, number, number]> = {
  chad: [37, 99, 235],
  allowAll: [234, 88, 12],
  selective: [13, 148, 136],
  off: [113, 113, 122],
  offline: [161, 161, 170],
};

export function trayIcon(mode: ModeId | 'offline', pending: number): NativeImage {
  const size = 32;
  const [r, g, b] = COLORS[mode];
  const pixels = Buffer.alloc(size * size * 4);
  const centre = (size - 1) / 2;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const distance = Math.hypot(x - centre, y - centre);
      // A filled disc; offline is a ring. A pending command adds a white dot.
      let alpha = Math.max(0, Math.min(1, 15.5 - distance));
      if (mode === 'offline') alpha *= Math.max(0, Math.min(1, distance - 9.5));
      let [pr, pg, pb] = [r, g, b];
      if (pending > 0 && Math.hypot(x - 23, y - 9) < 6.5) [pr, pg, pb, alpha] = [255, 255, 255, 1];
      const offset = (y * size + x) * 4;
      // Bitmaps are BGRA.
      pixels[offset] = pb;
      pixels[offset + 1] = pg;
      pixels[offset + 2] = pr;
      pixels[offset + 3] = Math.round(alpha * 255);
    }
  }
  return nativeImage.createFromBitmap(pixels, { width: size, height: size, scaleFactor: 2 });
}
