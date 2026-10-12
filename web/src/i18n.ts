/* Two languages on the interface. Vietnamese is the source: every string in the code is written in Vietnamese and is its
   own key; `en.ts` holds the English for each. A key with no English falls back to the Vietnamese, so a missing
   translation is never a blank. Vietnamese is the default until the operator picks English; the browser's own language
   is not consulted, since a Vietnamese operator on an English macOS is the common case. The language is chosen once at
   start-up (switching reloads the page), which lets constants built at module load, such as page names, carry the
   right words too. */
import en from "./en";

export type Lang = "vi" | "en";
const KEY = "nx.lang";

function detect(): Lang {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "vi" || stored === "en") return stored;
  } catch { /* private window */ }
  return "vi";
}

export const lang: Lang = detect();
document.documentElement.lang = lang;

/** The text for the current language. `{0}`, `{1}`… in the English stand for the arguments, in the order given. */
export function t(vi: string, ...args: unknown[]): string {
  const text = lang === "en" ? (en as Record<string, string>)[vi] ?? vi : vi;
  return args.length ? text.replace(/\{(\d+)\}/g, (_, i) => String(args[Number(i)] ?? "")) : text;
}

/** Vietnamese with the same `{0}` placeholders, for building a key out of a template. */
export const tv = (parts: TemplateStringsArray, ...args: unknown[]) => t(parts.raw.map((p, i) => (i < args.length ? `${p}{${i}}` : p)).join(""), ...args);

export function setLang(next: Lang) {
  try { localStorage.setItem(KEY, next); } catch { /* private window */ }
  window.location.reload();
}

/** The locale for dates and numbers. */
export const locale = lang === "en" ? "en-US" : "vi-VN";
