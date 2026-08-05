/**
 * Génère les icônes PNG de la PWA sans dépendance externe.
 * Encodeur PNG minimal : IHDR + IDAT (deflate) + IEND.
 *
 *   node scripts/make-icons.mjs
 */
import { deflateSync } from 'node:zlib';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');

const BG = [11, 13, 16];
const GOLD = [212, 164, 55];
const GOLD_DARK = [138, 108, 34];

function crc32(buf) {
  let c;
  const table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/** pixels: Uint8Array RGB, longueur size*size*3 */
function encodePng(size, pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: truecolor RGB
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  // Chaque ligne est préfixée de son type de filtre (0 = aucun).
  const stride = size * 3;
  const raw = Buffer.alloc(size * (stride + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0;
    pixels.copy
      ? Buffer.from(pixels).copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride)
      : raw.set(pixels.subarray(y * stride, (y + 1) * stride), y * (stride + 1) + 1);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/** Barreau d'or vu de face, stylisé : trapèze doré sur fond sombre. */
function draw(size) {
  const px = Buffer.alloc(size * size * 3);
  const set = (x, y, [r, g, b]) => {
    const i = (y * size + x) * 3;
    px[i] = r;
    px[i + 1] = g;
    px[i + 2] = b;
  };

  const s = size / 100; // unités relatives
  const barTop = 40 * s;
  const barBottom = 74 * s;
  const topHalf = 22 * s;
  const bottomHalf = 34 * s;
  const cx = size / 2;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let color = BG;

      if (y >= barTop && y <= barBottom) {
        const t = (y - barTop) / (barBottom - barTop);
        const half = topHalf + (bottomHalf - topHalf) * t;
        if (Math.abs(x - cx) <= half) {
          // Dégradé vertical léger pour donner du relief au lingot.
          const k = 1 - t * 0.35;
          color = [
            Math.round(GOLD[0] * k + GOLD_DARK[0] * (1 - k)),
            Math.round(GOLD[1] * k + GOLD_DARK[1] * (1 - k)),
            Math.round(GOLD[2] * k + GOLD_DARK[2] * (1 - k)),
          ];
        }
      }

      // Face supérieure du lingot, plus claire.
      if (y >= 32 * s && y < barTop && Math.abs(x - cx) <= topHalf + (barTop - y) * 0.15) {
        color = [
          Math.min(255, GOLD[0] + 30),
          Math.min(255, GOLD[1] + 26),
          Math.min(255, GOLD[2] + 20),
        ];
      }

      set(x, y, color);
    }
  }
  return px;
}

mkdirSync(OUT, { recursive: true });
for (const size of [192, 512, 180]) {
  const name = size === 180 ? 'apple-touch-icon.png' : `icon-${size}.png`;
  writeFileSync(join(OUT, name), encodePng(size, draw(size)));
  console.log(`écrit public/${name}`);
}
