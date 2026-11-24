const BASE = "/api";
export class ApiError extends Error {
  constructor(public status: number, public code: string, public detail?: any) { super(code); }
}
export const getToken = () => { try { return localStorage.getItem("token") || ""; } catch { return ""; } };
export const setToken = (t: string) => { try { t ? localStorage.setItem("token", t) : localStorage.removeItem("token"); } catch { /* private mode */ } };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** fetch with retry (network errors / 5xx on idempotent calls) and exponential backoff for weak networks. */
export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; retries?: number } = {}): Promise<T> {
  const method = opts.method || "GET";
  const retries = opts.retries ?? (method === "GET" ? 3 : 1);
  let last: any;
  for (let i = 0; i <= retries; i++) {
    try {
      const headers: Record<string, string> = {};
      const tok = getToken();
      if (tok) headers.Authorization = `Bearer ${tok}`;
      if (opts.body !== undefined) headers["Content-Type"] = "application/json";
      const r = await fetch(BASE + path, { method, headers, body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined) });
      if (r.status >= 500 && r.status !== 503 && i < retries) { await sleep(400 * 2 ** i); continue; }
      const ct = r.headers.get("content-type") || "";
      const data = ct.includes("json") ? await r.json() : r.ok ? await r.blob() : null;
      if (!r.ok) {
        const d = (data as any)?.detail;
        throw new ApiError(r.status, typeof d === "string" ? d : d?.code || `http_${r.status}`, typeof d === "object" ? d : undefined);
      }
      return data as T;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      last = e;
      if (i < retries) await sleep(400 * 2 ** i);
    }
  }
  throw new ApiError(0, "network", last);
}

export const isDegraded = (e: unknown) => e instanceof ApiError && (e.status === 503 || e.detail?.degraded);
