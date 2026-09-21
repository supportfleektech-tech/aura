import { lazy, Suspense } from "react";
import { HomeView, RightRail } from "./home";
import { StoreProvider, useStore } from "./store";
import { LangProvider } from "./i18n";
import { CommandPalette, ErrorBoundary, Sidebar, Toasts, TopBar } from "./ui";
import { CareerView, ClientsView, PersonalView } from "./views1";
const ActivityView = lazy(() => import("./views2").then((m) => ({ default: m.ActivityView })));
const AutomationsView = lazy(() => import("./views2").then((m) => ({ default: m.AutomationsView })));
const FilesView = lazy(() => import("./views2").then((m) => ({ default: m.FilesView })));
const GatewayView = lazy(() => import("./views2").then((m) => ({ default: m.GatewayView })));
const MemoryView = lazy(() => import("./views2").then((m) => ({ default: m.MemoryView })));
const SettingsView = lazy(() => import("./views2").then((m) => ({ default: m.SettingsView })));
const SmartHomeView = lazy(() => import("./views2").then((m) => ({ default: m.SmartHomeView })));
const VoiceView = lazy(() => import("./views2").then((m) => ({ default: m.VoiceView })));
const AnalyticsView = lazy(() => import("./views3").then((m) => ({ default: m.AnalyticsView })));
const CalendarView = lazy(() => import("./views3").then((m) => ({ default: m.CalendarView })));
const InboxView = lazy(() => import("./views3").then((m) => ({ default: m.InboxView })));
const SessionsView = lazy(() => import("./views3").then((m) => ({ default: m.SessionsView })));
const CallOverlay = lazy(() => import("./views4").then((m) => ({ default: m.CallOverlay })));
const FeedsView = lazy(() => import("./views4").then((m) => ({ default: m.FeedsView })));
const ModelsView = lazy(() => import("./views4").then((m) => ({ default: m.ModelsView })));
const TerminalView = lazy(() => import("./views4").then((m) => ({ default: m.TerminalView })));
import { OnboardingGate } from "./Onboarding";
import "./theme.css";

function Shell() {
  const { view, call } = useStore();
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Sidebar />
      <div className="main">
        <TopBar />
        <div className="content">
          <main className="center" id="main-content" tabIndex={-1}>
            <ErrorBoundary key={view}>
            <Suspense fallback={<div className="empty" role="status">Loading view…</div>}>
            {view === "home" && <HomeView />}
            {view === "career" && <CareerView />}
            {view === "clients" && <ClientsView />}
            {view === "personal" && <PersonalView />}
            {view === "inbox" && <InboxView />}
            {view === "calendar" && <CalendarView />}
            {view === "sessions" && <SessionsView />}
            {view === "memory" && <MemoryView />}
            {view === "voice" && <VoiceView />}
            {view === "gateway" && <GatewayView />}
            {view === "automations" && <AutomationsView />}
            {view === "activity" && <ActivityView />}
            {view === "analytics" && <AnalyticsView />}
            {view === "smarthome" && <SmartHomeView />}
            {view === "files" && <FilesView />}
            {view === "terminal" && <TerminalView />}
            {view === "models" && <ModelsView />}
            {view === "feeds" && <FeedsView />}
            {view === "settings" && <SettingsView />}
            </Suspense>
            </ErrorBoundary>
          </main>
          <RightRail />
        </div>
        <footer className="foot">
          <span>AURA OS v1.15.0 · Built with ♥ using Hermes Agent · Local LFM · Memory Engine · SQLite</span>
          <span>Smarter. Healthier. More Productive. — AURA OS</span>
        </footer>
      </div>
      <CommandPalette />
      <Toasts />
      <OnboardingGate />
      {call && <ErrorBoundary><Suspense fallback={<div className="empty" role="status">Loading call…</div>}><CallOverlay /></Suspense></ErrorBoundary>}
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <LangProvider>
        <StoreProvider>
          <Shell />
        </StoreProvider>
      </LangProvider>
    </ErrorBoundary>
  );
}
