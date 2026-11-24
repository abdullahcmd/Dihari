import { useState } from "react";
import { api, ApiError, setToken } from "../api";
import { BigButton, ScreenHeader, SpeakerButton, Stepper } from "../components/ui";
import { availableLocales, useI18n } from "../i18n";
import { useSession } from "../session";

export function FirstRun() {
  const { t, lang, setLang } = useI18n();
  const { setRole } = useSession();
  const names: Record<string, string> = { ur: "اردو", en: "English" };
  return (
    <div className="min-h-screen flex flex-col">
      <ScreenHeader title={t("ui.firstrun.title")} speakText={t("ui.firstrun.speak")} auto />
      <div className="flex gap-3 p-4 justify-center" role="group" aria-label={t("ui.lang.pick")}>
        {availableLocales.map((l) => (
          <button key={l} onClick={() => setLang(l)} className={`min-h-[56px] px-6 rounded-2xl text-xl font-bold border-4 ${l === lang ? "bg-brand text-white border-brand" : "border-gray-500"}`}>{names[l] || l}</button>
        ))}
      </div>
      <div className="flex-1 flex flex-col justify-center gap-6 p-4">
        <BigButton tone="blue" icon="🏗️" onClick={() => setRole("hirer")}>{t("ui.role.hirer")}</BigButton>
        <BigButton tone="green" icon="👷" onClick={() => setRole("worker")}>{t("ui.role.worker")}</BigButton>
      </div>
      <div className="p-4 flex justify-center"><SpeakerButton text={t("ui.firstrun.speak")} /></div>
    </div>
  );
}

export function Login() {
  const { t, lang } = useI18n();
  const { role, refresh, setRole } = useSession();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<{ dev_otp?: string } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true); setErr("");
    try { await fn(); } catch (e) { const a = e as ApiError; setErr(a.status === 0 ? t("ui.error.network") : a.status === 429 ? t("ui.error.rate_limited") : a.code === "invalid_phone" ? t("ui.login.bad_phone") : t("ui.login.bad_code")); }
    setBusy(false);
  };
  return (
    <div className="min-h-screen flex flex-col">
      <ScreenHeader title={t("ui.login.phone")} speakText={t("ui.login.speak")} />
      <div className="p-4 space-y-5">
        <input inputMode="tel" dir="ltr" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="03XX XXXXXXX"
          className="w-full text-3xl text-center rounded-2xl border-4 border-gray-600 min-h-[72px]" aria-label={t("ui.login.phone")} />
        {!sent && <BigButton disabled={busy || phone.length < 7} onClick={() => wrap(async () => setSent(await api("/auth/request-otp", { method: "POST", body: { phone } })))}>{t("ui.login.send")}</BigButton>}
        {sent && (
          <>
            <p className="text-xl font-bold">{t("ui.login.code")}</p>
            {sent.dev_otp && <button className="underline text-lg" onClick={() => setCode(sent.dev_otp!)}>{t("ui.login.devotp", { code: sent.dev_otp })}</button>}
            <input inputMode="numeric" dir="ltr" value={code} onChange={(e) => setCode(e.target.value)} maxLength={6}
              className="w-full text-4xl text-center tracking-widest rounded-2xl border-4 border-gray-600 min-h-[72px]" />
            <BigButton disabled={busy || code.length < 6} onClick={() => wrap(async () => {
              const r = await api<{ token: string }>("/auth/verify-otp", { method: "POST", body: { phone, code, role, locale: lang } });
              setToken(r.token); await refresh();
            })}>{t("ui.login.verify")}</BigButton>
          </>
        )}
        {err && <p role="alert" className="text-xl font-bold text-red-800">⚠️ {err}</p>}
        <button className="underline text-lg min-h-[56px]" onClick={() => setRole("")}>← {t("ui.back")}</button>
      </div>
    </div>
  );
}

export function ProfileForm({ onSaved }: { onSaved: () => void }) {
  const { t, lang } = useI18n();
  const { me, country, refresh } = useSession();
  const p = me?.profile || {};
  const [name, setName] = useState(me?.name || "");
  const [trades, setTrades] = useState<string[]>(p.trades || []);
  const [area, setArea] = useState<string>(p.area_name || "");
  const [radius, setRadius] = useState<number>(p.radius_km || country?.default_radius_km || 10);
  const [htype, setHtype] = useState<string>(p.hirer_type || "");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const worker = me?.role === "worker";
  const ok = worker ? trades.length > 0 && !!area : !!htype;
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      if (worker) await api("/profiles/worker", { method: "PUT", body: { name, trades, area_name: area, radius_km: radius } });
      else await api("/profiles/hirer", { method: "PUT", body: { name, hirer_type: htype } });
      await refresh(); onSaved();
    } catch (e) { setErr(e); }
    setBusy(false);
  };
  const chip = (on: boolean) => `min-h-[64px] px-4 rounded-2xl text-xl font-bold border-4 ${on ? "bg-brand text-white border-brand" : "border-gray-500 bg-white"}`;
  return (
    <div className="pb-8">
      <ScreenHeader title={t("ui.me.title")} speakText={worker ? t("ui.setup.speak_worker") : t("ui.setup.speak_hirer")} />
      <div className="p-4 space-y-6">
        <label className="block text-xl font-bold">{t("ui.setup.name")}
          <input value={name} onChange={(e) => setName(e.target.value)} className="mt-2 w-full text-2xl rounded-2xl border-4 border-gray-600 min-h-[64px] px-3" />
        </label>
        {worker ? (
          <>
            <section><h2 className="text-xl font-bold mb-2">{t("ui.setup.trades")}</h2>
              <div className="grid grid-cols-2 gap-3">
                {country?.trades.map((tr) => (
                  <button key={tr.code} className={chip(trades.includes(tr.code))} onClick={() => setTrades((x) => x.includes(tr.code) ? x.filter((c) => c !== tr.code) : [...x, tr.code])}>
                    <span aria-hidden className="text-2xl">{tr.icon}</span> {tr.names[lang] || tr.names.en}
                  </button>))}
              </div></section>
            <section><h2 className="text-xl font-bold mb-2">{t("ui.setup.area")}</h2>
              <div className="flex flex-wrap gap-3">{country?.places.map((pl) => <button key={pl.name} className={chip(area === pl.name)} onClick={() => setArea(pl.name)}>{pl.name}</button>)}</div></section>
            <section><h2 className="text-xl font-bold mb-2">{t("ui.setup.radius", { km: radius })}</h2>
              <Stepper value={radius} onChange={setRadius} min={2} max={country?.max_radius_km || 40} step={2} unit="km" /></section>
          </>
        ) : (
          <section><h2 className="text-xl font-bold mb-2">{t("ui.setup.hirer_type")}</h2>
            <div className="space-y-3">{["household", "contractor", "business"].map((h) => <button key={h} className={`${chip(htype === h)} w-full`} onClick={() => setHtype(h)}>{t(`ui.hirer_type.${h}`)}</button>)}</div></section>
        )}
        {!!err && <p role="alert" className="text-xl font-bold text-red-800">⚠️ {t("ui.error.generic")}</p>}
        <BigButton disabled={!ok || busy} icon="✅" onClick={save}>{t("ui.me.save")}</BigButton>
      </div>
    </div>
  );
}
