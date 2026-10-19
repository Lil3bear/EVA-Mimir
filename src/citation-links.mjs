export function citationEntry(destination, entries) {
  if (typeof destination !== "string" || !destination.startsWith("cite.")) return null;
  const exact = entries.filter(e => destination === `cite.${e.key}` || /^cite\.\d+@/.test(destination) && destination.slice(destination.indexOf("@") + 1) === e.key);
  return exact.length === 1 ? exact[0] : null;
}
