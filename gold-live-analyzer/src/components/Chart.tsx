'use client';

import { useEffect, useRef } from 'react';

import type { Signal } from '@/lib/engine/signals';
import type { Level } from '@/lib/market/levels';
import type { Candle } from '@/lib/market/types';

interface ChartProps {
  candles: Candle[];
  ema20: (number | null)[];
  ema50: (number | null)[];
  ema200: (number | null)[];
  levels: Level[];
  signal: Signal | null;
  label: string;
}

const COLORS = {
  bull: '#22c58b',
  bear: '#f0556c',
  grid: 'rgba(36, 48, 68, 0.6)',
  axis: '#8798b4',
  ema20: '#f0b429',
  ema50: '#5aa9ff',
  ema200: '#a78bfa',
  level: 'rgba(135, 152, 180, 0.45)',
};

const PADDING = { top: 14, right: 66, bottom: 24, left: 8 };
const MAX_BARS = 140;

/** Graphique en chandeliers dessine au canvas — pas de dependance externe. */
export function Chart({ candles, ema20, ema50, ema200, levels, signal, label }: ChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const draw = () => {
      const width = wrap.clientWidth;
      const height = wrap.clientHeight;
      if (width === 0 || height === 0) return;

      const dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const offset = Math.max(0, candles.length - MAX_BARS);
      const view = candles.slice(offset);
      if (view.length < 2) {
        ctx.fillStyle = COLORS.axis;
        ctx.font = '13px ui-sans-serif, system-ui';
        ctx.fillText('En attente de donnees...', 14, height / 2);
        return;
      }

      const plotW = width - PADDING.left - PADDING.right;
      const plotH = height - PADDING.top - PADDING.bottom;

      // Echelle verticale : bougies + moyennes + niveaux proches.
      let min = Infinity;
      let max = -Infinity;
      for (const c of view) {
        if (c.l < min) min = c.l;
        if (c.h > max) max = c.h;
      }
      const emaSlices = [ema20, ema50, ema200].map((s) => s.slice(offset));
      for (const slice of emaSlices) {
        for (const value of slice) {
          if (value === null) continue;
          if (value < min) min = value;
          if (value > max) max = value;
        }
      }
      if (signal) {
        for (const value of [signal.entry, signal.stopLoss, ...signal.takeProfits]) {
          if (value < min) min = value;
          if (value > max) max = value;
        }
      }

      const span = Math.max(max - min, 0.5);
      min -= span * 0.06;
      max += span * 0.06;
      const range = max - min;

      const x = (i: number) => PADDING.left + (i / (view.length - 1)) * plotW;
      const y = (price: number) => PADDING.top + ((max - price) / range) * plotH;

      // Grille + axe des prix.
      ctx.font = '10px ui-monospace, monospace';
      ctx.textBaseline = 'middle';
      const steps = 6;
      for (let i = 0; i <= steps; i++) {
        const price = min + (range * i) / steps;
        const py = y(price);
        ctx.strokeStyle = COLORS.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(PADDING.left, py);
        ctx.lineTo(width - PADDING.right, py);
        ctx.stroke();
        ctx.fillStyle = COLORS.axis;
        ctx.fillText(price.toFixed(2), width - PADDING.right + 6, py);
      }

      // Niveaux de reference.
      for (const level of levels) {
        if (level.price < min || level.price > max) continue;
        const py = y(level.price);
        ctx.strokeStyle = COLORS.level;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(PADDING.left, py);
        ctx.lineTo(width - PADDING.right, py);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Chandeliers.
      const slot = plotW / view.length;
      const bodyW = Math.max(1.5, Math.min(slot * 0.66, 11));
      for (let i = 0; i < view.length; i++) {
        const c = view[i];
        const px = x(i);
        const up = c.c >= c.o;
        const color = up ? COLORS.bull : COLORS.bear;

        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(px, y(c.h));
        ctx.lineTo(px, y(c.l));
        ctx.stroke();

        const openY = y(c.o);
        const closeY = y(c.c);
        const top = Math.min(openY, closeY);
        const bodyH = Math.max(Math.abs(closeY - openY), 1);
        ctx.fillStyle = color;
        ctx.fillRect(px - bodyW / 2, top, bodyW, bodyH);
      }

      // Moyennes mobiles.
      const drawLine = (slice: (number | null)[], color: string) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < slice.length && i < view.length; i++) {
          const value = slice[i];
          if (value === null) {
            started = false;
            continue;
          }
          const px = x(i);
          const py = y(value);
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        }
        ctx.stroke();
      };
      drawLine(emaSlices[0], COLORS.ema20);
      drawLine(emaSlices[1], COLORS.ema50);
      drawLine(emaSlices[2], COLORS.ema200);

      // Plan de trade du signal en cours.
      if (signal) {
        const plan: { price: number; color: string; text: string }[] = [
          { price: signal.entry, color: '#e8edf6', text: 'Entree' },
          { price: signal.stopLoss, color: COLORS.bear, text: 'SL' },
        ];
        signal.takeProfits.forEach((tp, i) => {
          plan.push({ price: tp, color: COLORS.bull, text: `TP${i + 1}` });
        });

        for (const line of plan) {
          if (line.price < min || line.price > max) continue;
          const py = y(line.price);
          ctx.strokeStyle = line.color;
          ctx.lineWidth = 1.2;
          ctx.setLineDash([6, 3]);
          ctx.beginPath();
          ctx.moveTo(PADDING.left, py);
          ctx.lineTo(width - PADDING.right, py);
          ctx.stroke();
          ctx.setLineDash([]);

          ctx.fillStyle = line.color;
          ctx.font = 'bold 9px ui-sans-serif, system-ui';
          ctx.fillText(line.text, PADDING.left + 4, py - 6);
        }
      }

      // Dernier prix.
      const lastCandle = view[view.length - 1];
      const lastY = y(lastCandle.c);
      const lastColor = lastCandle.c >= lastCandle.o ? COLORS.bull : COLORS.bear;
      ctx.fillStyle = lastColor;
      ctx.fillRect(width - PADDING.right + 2, lastY - 8, PADDING.right - 4, 16);
      ctx.fillStyle = '#0a0d14';
      ctx.font = 'bold 10px ui-monospace, monospace';
      ctx.fillText(lastCandle.c.toFixed(2), width - PADDING.right + 6, lastY);

      // Legende.
      ctx.fillStyle = COLORS.axis;
      ctx.font = '10px ui-sans-serif, system-ui';
      ctx.fillText(label, PADDING.left + 2, PADDING.top - 4);
      const legend: [string, string][] = [
        ['EMA20', COLORS.ema20],
        ['EMA50', COLORS.ema50],
        ['EMA200', COLORS.ema200],
      ];
      let lx = PADDING.left + 60;
      for (const [name, color] of legend) {
        ctx.fillStyle = color;
        ctx.fillRect(lx, PADDING.top - 8, 8, 2);
        ctx.fillStyle = COLORS.axis;
        ctx.fillText(name, lx + 12, PADDING.top - 4);
        lx += 58;
      }
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [candles, ema20, ema50, ema200, levels, signal, label]);

  return (
    <div ref={wrapRef} className="h-[340px] w-full">
      <canvas ref={canvasRef} />
    </div>
  );
}
