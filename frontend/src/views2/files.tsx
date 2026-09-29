import { useEffect, useRef, useState } from "react";
import { ago, api } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row, Skel } from "../ui";
import { Field } from "../views1";
import { WatchPanel } from "../views4";

const Src = ({ k, sources }: { k: string; sources: Record<string, string> }) =>
  sources[k] && sources[k] !== "default" ? <span className="kvsrc">{sources[k]}</span> : null;

export function LookPanel() {
  const { toast } = useStore();
  const { data: st } = useFetch(() => api.vision.status());
  const [q, setQ] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ description: string; model: string; ms: number } | null>(null);
  const [camOn, setCamOn] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  function stopStream() {
    try { streamRef.current?.getTracks().forEach((tr) => tr.stop()); } catch { /* noop */ }
    streamRef.current = null;
    setCamOn(false);
  }
  useEffect(() => () => stopStream(), []);
  async function send(blob: Blob | null) {
    if (!blob) { toast("Capture failed", "error"); return; }
    setBusy(true);
    try {
      const r = await api.vision.look(blob, q, remember);
      setResult(r);
      toast(`Described with ${r.model}`, "success");
    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
    finally { setBusy(false); }
  }
  function snap(video: HTMLVideoElement | null): Promise<Blob | null> {
    return new Promise((resolve) => {
      try {
        const v = video;
        if (!v || !v.videoWidth) { resolve(null); return; }
        const c = document.createElement("canvas");
        c.width = v.videoWidth; c.height = v.videoHeight;
        c.getContext("2d")?.drawImage(v, 0, 0);
        c.toBlob((b) => resolve(b), "image/jpeg", 0.85);
      } catch { resolve(null); }
    });
  }
  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      streamRef.current = stream;
      setCamOn(true);
      setTimeout(() => { if (videoRef.current) { videoRef.current.srcObject = stream; void videoRef.current.play().catch(() => undefined); } }, 50);
    } catch { toast("Camera unavailable", "error"); }
  }
  async function captureScreen() {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const v = document.createElement("video");
      v.srcObject = stream;
      await v.play().catch(() => undefined);
      await new Promise((r) => setTimeout(r, 400));
      const blob = await snap(v);
      stream.getTracks().forEach((tr) => tr.stop());
      await send(blob);
    } catch { toast("Screen capture cancelled or unavailable", "warn"); }
  }
  return (
    <Panel icon="eye" title="Look" sub="Live senses — camera or screen, described by vision">
      {!st && <Skel />}
      {st && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Pill c={st.available ? "green" : "amber"}>{st.available ? `vision ready \u00b7 ${st.ollama_online ? `ollama/${st.ollama_model}` : "cloud"}` : "no vision model"}</Pill>
        </div>
      )}
      {st && !st.available && <small className="dim">Start Ollama with {st.ollama_model} (or configure cloud vision) to switch this on.</small>}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Field value={q} onChange={(e) => setQ(e.target.value)} placeholder="What do you see? (optional question)" />
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {!camOn && <Btn small kind="violet" disabled={busy} onClick={() => void startCamera()}>\ud83d\udcf7 Camera</Btn>}
        {camOn && <Btn small kind="green" disabled={busy} onClick={async () => { const b = await snap(videoRef.current); stopStream(); await send(b); }}>{busy ? "Looking\u2026" : "Capture"}</Btn>}
        {camOn && <Btn small onClick={stopStream}>Cancel</Btn>}
        <Btn small disabled={busy} onClick={() => void captureScreen()}>\ud83d\udda5\ufe0f Screenshot</Btn>
        <label><Btn small disabled={busy}>\ud83d\udcce Upload frame<input type="file" accept="image/*" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) await send(f); e.target.value = ""; }} /></Btn></label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /><small>remember</small></label>
      </div>
      {camOn && <video ref={videoRef} style={{ width: "100%", maxHeight: 320, marginTop: 8, borderRadius: 8 }} muted playsInline />}
      {result && <Row icon="eye" title={`${result.model} \u00b7 ${result.ms}ms`} sub={result.description.slice(0, 400)} />}
    </Panel>
  );
}

export function FilesView() {
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.files.list());
  const { toast } = useStore();
  const [analysis, setAnalysis] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const analyze = async (id: number) => {
    setBusy(id);
    try {
      const r = await api.files.analyze(id);
      setAnalysis((a) => ({ ...a, [id]: r.description }));
      toast(`Described with ${r.model}`, "success");
    } catch (e) { toast(`Vision failed: ${e instanceof Error ? e.message : e}`, "error"); }
    finally { setBusy(null); }
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="folder" s={20} /> {t("title.files")}</h2></div>
      <LookPanel />
      <Panel icon="plus" title="Upload" sub="PDF \u00b7 DOCX \u00b7 CSV \u00b7 TXT \u00b7 images \u00b7 audio — text is indexed into memory">
        <input type="file" multiple onChange={async (e) => { if (!e.target.files?.length) return; await api.files.upload(e.target.files); toast("Uploaded & indexed", "success"); reload(); }} />
      </Panel>
      <Panel icon="folder" title="Library" sub={`${(data?.files || []).length} files`}>
        {(data?.files || []).map((f) => (
          <div key={f.id}>
            <Row icon={f.mime.startsWith("image") ? "image" : "file"} title={f.name} sub={`${(f.size / 1024).toFixed(1)} KB \u00b7 ${ago(f.created_at)}${(f.analysis_count || 0) > 0 ? ` \u00b7 \ud83d\udc41 ${f.analysis_count}` : ""}`}
              right={<span style={{ display: "inline-flex", gap: 6 }}>
                {f.mime.startsWith("image") && <Btn small disabled={busy === f.id} onClick={() => analyze(f.id)}>{busy === f.id ? "Seeing\u2026" : "Analyze"}</Btn>}
                <a className="btn sm" href={`/api/files/${f.id}`} download>Download</a>
              </span>} />
            {analysis[f.id] && <div className="muted" style={{ fontSize: 13, padding: "2px 4px 8px 40px" }}>{analysis[f.id]}</div>}
          </div>
        ))}
        {(data?.files || []).length === 0 && <Empty title="No files yet" sub="Upload documents for AURA to read." />}
      </Panel>
      <WatchPanel />
    </div>
  );
}
