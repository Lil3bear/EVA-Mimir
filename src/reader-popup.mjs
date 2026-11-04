export function placeReaderPopup(anchor, size, viewport) {
  const margin = 12;
  const left = Math.max(margin, Math.min(anchor.x, viewport.width - size.width - margin));
  const below = anchor.bottom + 8;
  const preferred = below + size.height <= viewport.height - margin ? below : anchor.top - size.height - 8;
  return { left, top: Math.max(margin, Math.min(preferred, viewport.height - size.height - margin)) };
}
