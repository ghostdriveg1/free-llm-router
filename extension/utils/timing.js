/**
 * @fileoverview Human-like timing utilities for realistic typing simulation.
 * Uses Box-Muller transform for Gaussian-distributed delays.
 * @module utils/timing
 */

/**
 * Generate a random number from a Gaussian (normal) distribution
 * using the Box-Muller transform.
 * @param {number} mean - The mean of the distribution.
 * @param {number} stdDev - The standard deviation.
 * @returns {number} A normally-distributed random value.
 */
export function gaussianRandom(mean, stdDev) {
  let u1 = 0, u2 = 0;
  // Avoid log(0)
  while (u1 === 0) u1 = Math.random();
  while (u2 === 0) u2 = Math.random();
  const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
  return mean + z * stdDev;
}

/**
 * Returns a Gaussian-distributed delay in milliseconds,
 * clamped to [min, max] to prevent unrealistic extremes.
 * @param {number} [mean=120] - Mean delay in ms.
 * @param {number} [stdDev=30] - Standard deviation in ms.
 * @param {number} [min=40] - Minimum clamp in ms.
 * @param {number} [max=350] - Maximum clamp in ms.
 * @returns {number} Delay in milliseconds.
 */
export function gaussianDelay(mean = 120, stdDev = 30, min = 40, max = 350) {
  const raw = gaussianRandom(mean, stdDev);
  return Math.round(Math.max(min, Math.min(max, raw)));
}

/**
 * Simulate a "thinking pause" — a longer pause that humans make
 * roughly 10% of the time while typing (e.g., between words or sentences).
 * @param {number} [probability=0.10] - Chance of a thinking pause (0–1).
 * @param {number} [minMs=300] - Minimum thinking pause in ms.
 * @param {number} [maxMs=1000] - Maximum thinking pause in ms.
 * @returns {number} Additional delay in ms (0 if no pause triggered).
 */
export function thinkingPause(probability = 0.10, minMs = 300, maxMs = 1000) {
  if (Math.random() > probability) return 0;
  return Math.round(minMs + Math.random() * (maxMs - minMs));
}

/**
 * Calculate the delay for typing a specific character.
 * Spaces and punctuation get slightly different timing profiles.
 * @param {string} char - The character being typed.
 * @returns {number} Delay in milliseconds before this character.
 */
export function humanTypeDelay(char) {
  // Base delay
  let mean = 120;
  let stdDev = 30;

  if (char === ' ') {
    // Spaces are slightly faster (muscle memory)
    mean = 80;
    stdDev = 20;
  } else if (/[.!?\n]/.test(char)) {
    // End-of-sentence punctuation → longer pause
    mean = 200;
    stdDev = 60;
  } else if (/[,;:]/.test(char)) {
    // Mid-sentence punctuation → moderate pause
    mean = 160;
    stdDev = 40;
  } else if (/[A-Z]/.test(char)) {
    // Uppercase letters → slight extra delay (shift key)
    mean = 140;
    stdDev = 35;
  }

  const baseDelay = gaussianDelay(mean, stdDev);
  const pause = thinkingPause();
  return baseDelay + pause;
}

/**
 * Sleep for the given number of milliseconds.
 * @param {number} ms - Duration to sleep.
 * @returns {Promise<void>}
 */
export function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Sleep for a human-like delay appropriate for the given character.
 * @param {string} char - The character about to be typed.
 * @returns {Promise<number>} Resolves with the actual delay used (ms).
 */
export async function sleepHumanDelay(char) {
  const delay = humanTypeDelay(char);
  await sleep(delay);
  return delay;
}
