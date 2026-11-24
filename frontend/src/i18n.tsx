import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Dict = Record<string, any>;
const loaders = import.meta.glob("../../locales/*.json") as Record<string, () => Promise<{ default: Dict }>>;
export const availableLocales = Object.keys(loaders).map((p) => p.match(/([^/]+)\.json$/)![1]);
const cache: Record<string, Dict> = {};

async function load(lang: string): Promise<Dict> {
  if (cache[lang]) return cache[lang];
  const key = Object.keys(loaders).find((k) => k.endsWith(`/${lang}.json`));
  cache[lang] = key ? (await loaders[key]()).default : {};
  return cache[lang];
}

interface Ctx { lang: string; setLang: (l: string) => void; t: (k: string, p?: Record<string, string | number>) => string; dir: "rtl" | "ltr"; bcp47: string; ready: boolean }
const I18nCtx = createContext<Ctx>(null as any);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState(() => { try { return localStorage.getItem("lang") || "ur"; } catch { return "ur"; } });
  const [dicts, setDicts] = useState<Dict[]>([]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.all([load(lang), load("en")]).then((d) => { if (live) { setDicts(d); setReady(true); } });
    return () => { live = false; };
  }, [lang]);
  const meta = dicts[0]?._meta || {};
  const dir = (meta.dir || "rtl") as "rtl" | "ltr";
  useEffect(() => { document.documentElement.lang = lang; document.documentElement.dir = dir; }, [lang, dir]);
  const value = useMemo<Ctx>(() => ({
    lang, dir, ready, bcp47: meta.bcp47 || lang,
    setLang: (l) => { try { localStorage.setItem("lang", l); } catch { /* ignore */ } setLangState(l); },
    t: (k, p) => {
      let s = dicts.map((d) => d[k]).find((v) => typeof v === "string") ?? k;
      if (p) for (const [a, b] of Object.entries(p)) s = s.split(`{${a}}`).join(String(b));
      return s;
    },
  }), [lang, dicts, dir, ready]);
  return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>;
}
export const useI18n = () => useContext(I18nCtx);
