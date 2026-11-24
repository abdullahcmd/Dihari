import { api, isDegraded } from "./api";

export interface Caps { asr: { available: boolean; real: boolean }; tts: { available: boolean; real: boolean } }
let caps: Caps | null = null;
export async function capabilities(): Promise<Caps> {
  if (caps) return caps;
  try { caps = await api<Caps>("/ai/capabilities", { retries: 1 }); } catch { caps = { asr: { available: false, real: false }, tts: { available: false, real: false } }; }
  return caps!;
}

let current: HTMLAudioElement | null = null;
export function stopSpeaking() {
  current?.pause(); current = null;
  try { window.speechSynthesis?.cancel(); } catch { /* */ }
}

/** Read text aloud: server TTS if a real provider is configured, else browser speechSynthesis. Never throws. */
export async function speak(text: string, bcp47: string, lang: string): Promise<void> {
  stopSpeaking();
  const c = await capabilities();
  if (c.tts.real) {
    try {
      const blob = await api<Blob>("/ai/tts", { method: "POST", body: { text, lang }, retries: 0 });
      const a = new Audio(URL.createObjectURL(blob)); current = a;
      await a.play();
      return;
    } catch (e) { /* fall through to browser voice */ void isDegraded(e); }
  }
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = bcp47; u.rate = 0.9;
    window.speechSynthesis.speak(u);
  } catch { /* silent: visual fallback always exists */ }
}

export const canListen = () => !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || (typeof MediaRecorder !== "undefined" && navigator.mediaDevices));

export interface Listener { stop: () => void; result: Promise<string> }

/** Start listening. Server ASR (MediaRecorder) when real, else browser SpeechRecognition. Rejects 'unsupported' → UI shows typing. */
export async function listen(bcp47: string, lang: string): Promise<Listener> {
  const c = await capabilities();
  if (c.asr.real && typeof MediaRecorder !== "undefined") {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream); const chunks: Blob[] = [];
    rec.ondataavailable = (e) => chunks.push(e.data);
    const result = new Promise<string>((resolve, reject) => {
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        try {
          const form = new FormData(); form.append("audio", new Blob(chunks, { type: rec.mimeType }), "a.webm"); form.append("lang", lang);
          resolve((await api<{ text: string }>("/ai/transcribe", { method: "POST", form, retries: 1 })).text);
        } catch (e) { reject(e); }
      };
    });
    rec.start();
    return { stop: () => rec.state !== "inactive" && rec.stop(), result };
  }
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) throw new Error("unsupported");
  const r = new SR(); r.lang = bcp47; r.interimResults = false; r.maxAlternatives = 1;
  const result = new Promise<string>((resolve, reject) => {
    r.onresult = (e: any) => resolve(e.results[0][0].transcript);
    r.onerror = (e: any) => reject(new Error(e.error || "speech_error"));
    r.onend = () => reject(new Error("no_speech"));
  });
  r.start();
  return { stop: () => { try { r.stop(); } catch { /* */ } }, result };
}
