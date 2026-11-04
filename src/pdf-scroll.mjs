export function pageAtReadingLine(pages, viewportTop, viewportHeight) {
  if (!pages.length) return 1;
  const line = viewportTop + Math.min(200, viewportHeight * 0.35);
  const containing = pages.find(p => p.top <= line && p.bottom > line);
  if (containing) return containing.page;
  return pages.reduce((best, p) => Math.abs(p.top - line) < Math.abs(best.top - line) ? p : best).page;
}
