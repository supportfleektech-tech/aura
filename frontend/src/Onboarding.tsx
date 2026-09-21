/* AURA OS first-run onboarding — master plan §83 (7 progressive steps) + §84 demo.
 * Shown once: gated on the server `onboarded` setting. Every step writes real
 * settings/identity/goal/project rows; finishing sets onboarded=true. */
import { useEffect, useState } from "react";
import { api } from "./api";
import { useLang } from "./i18n";
import { getServer, loadServerSettings, serverLoaded, setServerCache } from "./prefs";
import { useStore } from "./store";
import { Btn, Panel, Pill, Progress, Seg, SetRow, Toggle } from "./ui";
import { useFetch } from "./views1";
import { pushSupported, subscribePush } from "./push";

export const ONBOARD_ZONES = [
  "Africa/Nairobi", "UTC", "Africa/Lagos", "Africa/Cairo", "Africa/Johannesburg",
  "Europe/London", "Europe/Paris", "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata",
  "Asia/Singapore", "Australia/Sydney", "Pacific/Auckland",
  "America/New_York", "America/Chicago", "America/Los_Angeles",
];
const ZONES = ONBOARD_ZONES;
const KEY_FOR: Record<string, string> = {
  openrouter: "openrouter_key", openai: "openai_key", custom: "custom_key",
};
const DEMO_PROMPT = "Show me what needs my attention today";

export function OnboardingGate() {
  const [show, setShow] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    loadServerSettings()
      .then(() => { if (serverLoaded()) setShow(!getServer("onboarded", true)); })
      .catch(() => undefined)
      .finally(() => setReady(true));
  }, []);
  if (!ready || !show) return null;
  return <OnboardingWizard onDone={() => setShow(false)} />;
}

export function OnboardingWizard({ onDone }: { onDone: () => void }) {
  const { t } = useLang();
  const { toast, send } = useStore();
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  // step 1 — identity
  const meQ = useFetch(() => api.me.get(), []);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [loc, setLoc] = useState("");
  const [tz, setTz] = useState<string>(() => getServer("timezone", "Africa/Nairobi"));
  useEffect(() => {
    if (meQ.data) {
      setName(meQ.data.name || "");
      setRole(meQ.data.role || "");
      setLoc(meQ.data.location || "");
    }
  }, [meQ.data]);

  // step 2 — domains
  const [dCareer, setDCareer] = useState(() => getServer("domain_career", true));
  const [dClients, setDClients] = useState(() => getServer("domain_clients", true));
  const [dPersonal, setDPersonal] = useState(() => getServer("domain_personal", true));
  // step 3 — memory
  const [memAuto, setMemAuto] = useState(() => getServer("memory_auto_store", true));
  const [memPol, setMemPol] = useState<string>(() => getServer("cloud_memory_policy", "strict"));
  // step 4 — intelligence
  const [privacy, setPrivacy] = useState<string>(() => getServer("privacy", "local-first"));
  const [provider, setProvider] = useState<string>(() => getServer("cloud_provider", "openrouter"));
  const [key, setKey] = useState("");
  // step 5 — platforms
  const gwQ = useFetch(() => api.gateway.status(), []);
  // step 6 — notifications
  const [qStart, setQStart] = useState(() => getServer("quiet_start", ""));
  const [qEnd, setQEnd] = useState(() => getServer("quiet_end", ""));
  // step 7 — first content
  const [goal, setGoal] = useState("");
  const [project, setProject] = useState("");

  const save = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      setStep((s) => s + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setBusy(true);
    try {
      if (goal.trim()) await api.personal.goal({ title: goal.trim() });
      if (project.trim()) await api.projects.create({ name: project.trim() });
      const r = await api.settings.update({ onboarded: true });
      setServerCache(r.values as Record<string, unknown>);
      setDone(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const nexts: (() => void)[] = [
    () => void save(async () => {
      if (!name.trim()) throw new Error("Name is required");
      const body: Record<string, string> = { name: name.trim() };
      if (role.trim()) body.role = role.trim();
      if (loc.trim()) body.location = loc.trim();
      await api.me.update(body);
      const r = await api.settings.update({ timezone: tz });
      setServerCache(r.values as Record<string, unknown>);
    }),
    () => void save(async () => {
      const r = await api.settings.update({ domain_career: dCareer, domain_clients: dClients, domain_personal: dPersonal });
      setServerCache(r.values as Record<string, unknown>);
    }),
    () => void save(async () => {
      const r = await api.settings.update({ memory_auto_store: memAuto, cloud_memory_policy: memPol });
      setServerCache(r.values as Record<string, unknown>);
    }),
    () => void save(async () => {
      const body: Record<string, unknown> = { privacy, cloud_provider: provider };
      if (privacy !== "local-first" && key.trim()) body[KEY_FOR[provider]] = key.trim();
      const r = await api.settings.update(body);
      setServerCache(r.values as Record<string, unknown>);
    }),
    () => setStep((s) => s + 1),
    () => void save(async () => {
      const r = await api.settings.update({ quiet_start: qStart, quiet_end: qEnd });
      setServerCache(r.values as Record<string, unknown>);
    }),
    () => void finish(),
  ];

  const bodies: React.ReactNode[] = [
    <div key="s1">
      <SetRow title={t("ob.name")} control={<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Antony" />} />
      <SetRow title={t("ob.role")} control={<input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Builder" />} />
      <SetRow title={t("ob.location")} control={<input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="Nairobi, Kenya" />} />
      <SetRow title={t("ob.timezone")} control={
        <select value={tz} onChange={(e) => setTz(e.target.value)}>
          {ZONES.map((z) => <option key={z} value={z}>{z}</option>)}
        </select>
      } />
    </div>,
    <div key="s2">
      <SetRow title={t("ob.career")} control={<Toggle on={dCareer} onFlip={() => setDCareer(!dCareer)} label={t("ob.career")} />} />
      <SetRow title={t("ob.clients")} control={<Toggle on={dClients} onFlip={() => setDClients(!dClients)} label={t("ob.clients")} />} />
      <SetRow title={t("ob.personal")} control={<Toggle on={dPersonal} onFlip={() => setDPersonal(!dPersonal)} label={t("ob.personal")} />} />
    </div>,
    <div key="s3">
      <SetRow title={t("ob.memauto")} control={<Toggle on={memAuto} onFlip={() => setMemAuto(!memAuto)} label={t("ob.memauto")} />} />
      <SetRow title={t("ob.mempol")} control={
        <Seg options={[{ v: "strict", label: t("ob.strict") }, { v: "relaxed", label: t("ob.relaxed") }]}
          value={memPol} onPick={setMemPol} />
      } />
    </div>,
    <div key="s4">
      <SetRow title="Privacy" control={
        <Seg options={[{ v: "local-first", label: "Local" }, { v: "hybrid", label: "Hybrid" }, { v: "cloud", label: "Cloud" }]}
          value={privacy} onPick={setPrivacy} />
      } />
      {privacy !== "local-first" && (
        <>
          <SetRow title="Provider" control={
            <Seg options={[{ v: "openrouter", label: "OpenRouter" }, { v: "openai", label: "OpenAI" }, { v: "custom", label: "Custom" }]}
              value={provider} onPick={setProvider} />
          } />
          <SetRow title={t("ob.key")} control={
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-…" autoComplete="off" />
          } />
        </>
      )}
    </div>,
    <div key="s5">
      {(gwQ.data?.integrations || []).map((g) => (
        <SetRow key={g.platform} title={g.platform}
          sub={g.status === "connected" ? (g.account || g.mode || "connected") : g.status}
          control={g.status === "connected"
            ? <Pill c="green">{g.status}</Pill>
            : <Btn small onClick={() => { api.gateway.connect(g.platform, { mode: "sandbox" }).then(() => gwQ.reload()).catch((e) => toast(String(e), "error")); }}>{t("ob.connect")}</Btn>} />
      ))}
      {!gwQ.data && <p className="dim">…</p>}
    </div>,
    <div key="s6">
      <SetRow title={t("ob.quiet")} control={
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input type="time" value={qStart} onChange={(e) => setQStart(e.target.value)} aria-label="quiet start" />
          <small className="dim">→</small>
          <input type="time" value={qEnd} onChange={(e) => setQEnd(e.target.value)} aria-label="quiet end" />
        </span>
      } />
      {pushSupported() && (
        <SetRow title="Push" control={
          <Btn small kind="violet" onClick={() => { subscribePush().then(() => toast("Push enabled", "success")).catch((e) => toast(e instanceof Error ? e.message : String(e), "error")); }}>{t("ob.enablepush")}</Btn>
        } />
      )}
    </div>,
    <div key="s7">
      <SetRow title={t("ob.goal")} control={<input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Ship v1" />} />
      <SetRow title={t("ob.project")} control={<input value={project} onChange={(e) => setProject(e.target.value)} placeholder="NORERN" />} />
    </div>,
  ];
  const titles = [t("ob.s1t"), t("ob.s2t"), t("ob.s3t"), t("ob.s4t"), t("ob.s5t"), t("ob.s6t"), t("ob.s7t")];
  const descs = [t("ob.s1d"), t("ob.s2d"), t("ob.s3d"), t("ob.s4d"), t("ob.s5d"), t("ob.s6d"), t("ob.s7d")];

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 200, display: "grid", placeItems: "center", padding: 16, background: "rgba(4,8,18,.72)", backdropFilter: "blur(6px)" }}>
      <div style={{ width: "100%", maxWidth: 560, maxHeight: "92vh", overflowY: "auto" }}>
        <Panel icon="spark" title={done ? t("ob.done") : t("ob.title")}
          sub={done ? "" : `${t("ob.step")} ${step + 1} / 7`}>
          {!done && <Progress v={((step + 1) / 7) * 100} />}
          {!done && <h3 style={{ margin: "10px 0 2px" }}>{titles[step]}</h3>}
          {!done && <p className="dim" style={{ marginTop: 0 }}>{descs[step]}</p>}
          {!done && bodies[step]}
          {!done && (
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "space-between" }}>
              <Btn small onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>{t("ob.back")}</Btn>
              <Btn small kind="violet" onClick={nexts[step]} disabled={busy}>{t("ob.next")}</Btn>
            </div>
          )}
          {done && (
            <div>
              <p>{t("ob.demo")}</p>
              <p className="dim">“{DEMO_PROMPT}”</p>
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <Btn small kind="violet" onClick={() => { onDone(); void send(DEMO_PROMPT); }}>{t("ob.tryit")}</Btn>
                <Btn small onClick={onDone}>{t("ob.start")}</Btn>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
