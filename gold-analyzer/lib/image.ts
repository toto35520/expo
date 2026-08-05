/**
 * Compression des captures d'écran côté navigateur.
 *
 * Deux raisons :
 *  - Vercel plafonne le corps d'une requête serverless à ~4,5 Mo ;
 *  - au-delà de 2576 px sur le grand côté, l'API redimensionne de toute façon,
 *    donc les pixels supplémentaires ne sont que du poids et du coût.
 */

export const MAX_EDGE = 2576;
export const MAX_TOTAL_BYTES = 3_400_000;

export interface PreparedImage {
  dataUrl: string;
  mediaType: string;
  bytes: number;
  width: number;
  height: number;
}

export async function prepareImage(file: File): Promise<PreparedImage> {
  const bitmap = await loadBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas indisponible sur cet appareil.');
  ctx.imageSmoothingQuality = 'high';
  // Fond opaque : un PNG transparent deviendrait noir en JPEG.
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  if ('close' in bitmap) (bitmap as ImageBitmap).close?.();

  // Qualité dégressive jusqu'à passer sous ~1 Mo par image.
  let quality = 0.9;
  let dataUrl = canvas.toDataURL('image/jpeg', quality);
  while (dataUrlBytes(dataUrl) > 1_000_000 && quality > 0.5) {
    quality -= 0.1;
    dataUrl = canvas.toDataURL('image/jpeg', quality);
  }

  return {
    dataUrl,
    mediaType: 'image/jpeg',
    bytes: dataUrlBytes(dataUrl),
    width: w,
    height: h,
  };
}

export function dataUrlBytes(dataUrl: string): number {
  const i = dataUrl.indexOf(',');
  const b64 = i >= 0 ? dataUrl.slice(i + 1) : dataUrl;
  return Math.floor((b64.length * 3) / 4);
}

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file);
    } catch {
      /* Safari ancien : on retombe sur <img> */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Image illisible.'));
      img.src = url;
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

/** Devine le timeframe depuis le nom de fichier (TradingView le met dedans). */
export function guessTimeframe(filename: string): string {
  const n = filename.toUpperCase();
  const patterns: Array<[RegExp, string]> = [
    [/\b(1W|WEEKLY|W1)\b/, 'W1'],
    [/\b(1D|DAILY|D1)\b/, 'D1'],
    [/\b(4H|H4|240)\b/, 'H4'],
    [/\b(1H|H1|60)\b/, 'H1'],
    [/\b(30M|M30|30)\b/, 'M30'],
    [/\b(15M|M15|15)\b/, 'M15'],
    [/\b(5M|M5|5)\b/, 'M5'],
    [/\b(1M|M1)\b/, 'M1'],
  ];
  for (const [re, tf] of patterns) if (re.test(n)) return tf;
  return '';
}
