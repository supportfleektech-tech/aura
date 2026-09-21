/* PWA install prompt capture. */
let deferred: { prompt: () => void; userChoice: Promise<{ outcome: string }> } | null = null;

export function initInstallPrompt(onChange: (ready: boolean) => void) {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as unknown as typeof deferred;
    onChange(true);
  });
  window.addEventListener("appinstalled", () => { deferred = null; onChange(false); });
}

export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false;
  deferred.prompt();
  try {
    const { outcome } = await deferred.userChoice;
    if (outcome === "accepted") deferred = null;
    return outcome === "accepted";
  } catch {
    return false;
  }
}
