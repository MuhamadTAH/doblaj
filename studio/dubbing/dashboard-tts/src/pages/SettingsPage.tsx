import React, { useState } from "react";
import { useUser, useClerk } from "@clerk/clerk-react";
import { useNavigate } from "react-router-dom";
import { useApi, HttpError, AuthFailedError, AuthNetworkError } from "@/hooks/useApi";
import { useUiStore } from "@/store/ui";
import { locale, dir, t } from "@/lib/i18n";

type SettingsTab = "general" | "appearance" | "audio" | "notifications" | "billing" | "connections";

export default function SettingsPage() {
  const { user } = useUser();
  const { signOut } = useClerk();
  const navigate = useNavigate();
  const api = useApi();

  const {
    theme,
    toggleTheme,
    audioDefaults,
    setAudioDefaults,
    notifications,
    setNotifications,
  } = useUiStore();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [password, setPassword] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState("");

  const [isConnecting, setIsConnecting] = useState(false);
  const [telegramError, setTelegramError] = useState("");

  const handleDelete = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsDeleting(true);
    setMessage("");

    try {
      await api.deleteAccount(password);
      setMessage("Your account has been queued for deletion.");
      setTimeout(() => {
        window.location.href = "/";
      }, 2000);
    } catch (err) {
      if (err instanceof HttpError) {
        setMessage(err.detail || "Failed to delete account.");
      } else if (err instanceof AuthFailedError) {
        setMessage("Authentication failed. Please log in again.");
      } else if (err instanceof AuthNetworkError) {
        setMessage("Network error during authentication.");
      } else {
        setMessage("Error communicating with the server.");
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const handleConnectTelegram = async () => {
    setIsConnecting(true);
    setTelegramError("");
    try {
      const data = await api.getTelegramLinkNonce();
      if (data.nonce) {
        window.open(`https://t.me/dolajbot?start=${data.nonce}`, "_blank");
      } else {
        setTelegramError("Invalid response from server.");
      }
    } catch (err: any) {
      setTelegramError("Failed to generate Telegram connection link.");
    } finally {
      setIsConnecting(false);
    }
  };

  const handleLanguageChange = (newLang: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("lang", newLang);
    window.location.href = url.toString();
  };

  return (
    <div className="p-8 max-w-4xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-2">{t("nav_settings", "Account & App Settings")}</h1>
      <p className="text-ink-400 text-sm mb-6">
        {t("settings_subtitle", "Manage your profile, application defaults, language, and connected integrations.")}
      </p>

      {/* Tabs Bar */}
      <div className="flex border-b border-gray-800 mb-8 overflow-x-auto gap-2">
        <TabButton id="general" label="General" activeTab={activeTab} onClick={setActiveTab} />
        <TabButton id="appearance" label="Appearance & Language" activeTab={activeTab} onClick={setActiveTab} />
        <TabButton id="audio" label="Audio Defaults" activeTab={activeTab} onClick={setActiveTab} />
        <TabButton id="notifications" label="Notifications" activeTab={activeTab} onClick={setActiveTab} />
        <TabButton id="billing" label="Billing & Plan" activeTab={activeTab} onClick={setActiveTab} />
        <TabButton id="connections" label="Connections" activeTab={activeTab} onClick={setActiveTab} />
      </div>

      {/* General Tab */}
      {activeTab === "general" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Profile</h2>
            <div className="flex flex-col gap-4">
              <div>
                <label className="block text-sm font-medium text-ink-400 mb-1">Email Address</label>
                <div className="text-white font-medium bg-gray-800/50 border border-gray-700/50 rounded px-3 py-2 w-full max-w-md">
                  {user?.primaryEmailAddress?.emailAddress || "Loading..."}
                </div>
              </div>
              <div className="mt-2">
                <button
                  onClick={() => signOut()}
                  className="bg-white/10 hover:bg-white/20 border border-white/20 text-white font-semibold py-2 px-6 rounded transition-colors w-max"
                >
                  Sign Out
                </button>
              </div>
            </div>
          </div>

          <div className="border border-red-500/50 rounded-lg p-6 bg-red-900/10">
            <h2 className="text-xl font-bold text-red-500 mb-2">Delete My Data</h2>
            <p className="text-red-300/80 mb-4 text-sm">
              This action is permanent and cannot be undone. All your voice models, generated audio, and video projects will be deleted. Some transactional records may be retained for legal compliance.
            </p>

            {message && (
              <div className="mb-4 p-3 bg-red-900/50 text-red-200 rounded text-sm">
                {message}
              </div>
            )}

            <form onSubmit={handleDelete} className="flex flex-col gap-4">
              <div className="max-w-md">
                <label className="block text-sm font-medium mb-1 text-ink-400">Confirm Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-red-500"
                  required
                />
              </div>
              <button
                type="submit"
                disabled={isDeleting}
                className="bg-red-600/90 hover:bg-red-600 text-white font-semibold py-2 px-6 rounded w-max transition-colors disabled:opacity-50"
              >
                {isDeleting ? "Deleting..." : "Permanently Delete Account"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Appearance & Language Tab */}
      {activeTab === "appearance" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6 space-y-6">
            <h2 className="text-xl font-bold">Theme & Interface</h2>
            <div className="flex items-center justify-between py-2 border-b border-white/[0.06]">
              <div>
                <div className="font-semibold text-white">Color Theme</div>
                <div className="text-xs text-ink-400">Switch between dark and light workspace theme</div>
              </div>
              <button
                onClick={toggleTheme}
                className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 border border-white/20 text-white text-sm font-medium transition-colors capitalize flex items-center gap-2"
              >
                <span>{theme === "dark" ? "🌙 Dark Mode" : "☀️ Light Mode"}</span>
              </button>
            </div>

            <div className="space-y-4 pt-2">
              <h2 className="text-xl font-bold">Language & Region</h2>
              <div className="max-w-md">
                <label className="block text-sm font-medium text-ink-400 mb-2">Display Language</label>
                <select
                  value={locale}
                  onChange={(e) => handleLanguageChange(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none cursor-pointer"
                >
                  <option value="en">English (English)</option>
                  <option value="ckb">Kurdish Sorani (سۆرانی)</option>
                  <option value="ar">Iraqi Arabic (عربي عراقي)</option>
                </select>
              </div>
              <div className="text-xs text-ink-400">
                Active Text Direction: <span className="text-brand-300 font-mono font-semibold uppercase">{dir}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Audio Defaults Tab */}
      {activeTab === "audio" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6 space-y-6">
            <div>
              <h2 className="text-xl font-bold mb-1">Text-to-Speech & Dubbing Defaults</h2>
              <p className="text-xs text-ink-400">Default options automatically applied when starting a new generation.</p>
            </div>

            <div className="max-w-md">
              <label className="block text-sm font-medium text-ink-400 mb-2">Default TTS Engine Model</label>
              <select
                value={audioDefaults.model}
                onChange={(e) => setAudioDefaults({ model: e.target.value })}
                className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none cursor-pointer"
              >
                <option value="Fish Audio S2 Pro">Fish Audio S2 Pro (Recommended)</option>
                <option value="Fish Audio S1">Fish Audio S1</option>
                <option value="Fish Audio S2">Fish Audio S2</option>
              </select>
            </div>

            <div className="space-y-4 max-w-md pt-2">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-ink-400">Default Volume</span>
                  <span className="font-mono text-brand-300">{audioDefaults.volume > 0 ? `+${audioDefaults.volume}` : audioDefaults.volume}</span>
                </div>
                <input
                  type="range"
                  min="-5"
                  max="5"
                  step="1"
                  value={audioDefaults.volume}
                  onChange={(e) => setAudioDefaults({ volume: Number(e.target.value) })}
                  className="w-full accent-brand-400 cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-ink-400">Default Speed</span>
                  <span className="font-mono text-brand-300">{audioDefaults.speed.toFixed(2)}x</span>
                </div>
                <input
                  type="range"
                  min="0.7"
                  max="1.3"
                  step="0.05"
                  value={audioDefaults.speed}
                  onChange={(e) => setAudioDefaults({ speed: Number(e.target.value) })}
                  className="w-full accent-brand-400 cursor-pointer"
                />
              </div>
            </div>

            <div className="space-y-3 pt-4 border-t border-white/[0.06]">
              <ToggleRow
                label="Loudness Normalization"
                description="Automatically balance output audio loudness level"
                checked={audioDefaults.loudnessNorm}
                onChange={(v) => setAudioDefaults({ loudnessNorm: v })}
              />
              <ToggleRow
                label="Text Normalization"
                description="Convert numbers, symbols, and dates to spoken words"
                checked={audioDefaults.textNorm}
                onChange={(v) => setAudioDefaults({ textNorm: v })}
              />
              <ToggleRow
                label="Tag Compatible Mode"
                description="Preserve SSML / emotion tags in prompt text"
                checked={audioDefaults.tagCompat}
                onChange={(v) => setAudioDefaults({ tagCompat: v })}
              />
            </div>
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === "notifications" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6 space-y-6">
            <h2 className="text-xl font-bold mb-4">Notification Preferences</h2>
            <div className="space-y-4">
              <ToggleRow
                label="Generation & Dubbing Completed"
                description="Receive alerts when long video dubbing or batch audio generation completes"
                checked={notifications.notifyJobComplete}
                onChange={(v) => setNotifications({ notifyJobComplete: v })}
              />
              <ToggleRow
                label="Low Credit Warnings"
                description="Get notified when remaining generation credits drop below 10%"
                checked={notifications.notifyLowCredits}
                onChange={(v) => setNotifications({ notifyLowCredits: v })}
              />
              <ToggleRow
                label="Telegram Bot Notifications"
                description="Receive status updates and task results via @dolajbot"
                checked={notifications.telegramUpdates}
                onChange={(v) => setNotifications({ telegramUpdates: v })}
              />
            </div>
          </div>
        </div>
      )}

      {/* Billing & Plan Tab */}
      {activeTab === "billing" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-bold">Current Subscription</h2>
                <p className="text-ink-400 text-sm">Manage your billing method, view usage, and upgrade plan.</p>
              </div>
              <span className="text-xs font-semibold bg-emerald-500/20 text-emerald-300 px-3 py-1 rounded-full uppercase border border-emerald-500/30">
                Free Tier
              </span>
            </div>

            <div className="bg-white/[0.02] border border-white/[0.06] rounded-lg p-4 mb-6 flex flex-wrap justify-between items-center gap-4">
              <div>
                <div className="text-xs text-ink-400">Voice Generation Credits</div>
                <div className="text-2xl font-bold text-white mt-0.5">5,000 / month</div>
              </div>
              <button
                onClick={() => navigate("/billing")}
                className="bg-brand-500 hover:bg-brand-600 text-white font-semibold py-2 px-5 rounded-lg text-sm transition-colors"
              >
                Manage Billing & Usage
              </button>
            </div>

            <div className="flex gap-4">
              <button
                onClick={() => navigate("/pricing")}
                className="bg-gradient-to-r from-amber-400 to-amber-500 hover:from-amber-300 hover:to-amber-400 text-amber-950 font-bold py-2.5 px-6 rounded-lg text-sm transition-all"
              >
                ✦ Upgrade to Pro Plan
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Connections Tab */}
      {activeTab === "connections" && (
        <div className="space-y-8 animate-fade-in">
          <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-xl font-bold mb-2">Telegram Integration</h2>
                <p className="text-ink-300 text-sm max-w-md mb-6">
                  Connect your Telegram account to upload videos, receive dubbing updates, and manage your tasks directly through our official Telegram bot (@dolajbot).
                </p>
                {telegramError && (
                  <div className="mb-4 p-3 bg-red-900/50 border border-red-500/50 text-red-200 rounded text-sm max-w-md">
                    {telegramError}
                  </div>
                )}
                <button
                  onClick={handleConnectTelegram}
                  disabled={isConnecting}
                  className="bg-[#24A1DE] hover:bg-[#2090C7] text-white font-semibold py-2 px-6 rounded transition-colors w-max flex items-center gap-2 disabled:opacity-50"
                >
                  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.892-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
                  </svg>
                  {isConnecting ? "Connecting..." : "Connect Telegram"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TabButton({
  id,
  label,
  activeTab,
  onClick,
}: {
  id: SettingsTab;
  label: string;
  activeTab: SettingsTab;
  onClick: (t: SettingsTab) => void;
}) {
  const active = activeTab === id;
  return (
    <button
      onClick={() => onClick(id)}
      className={`px-4 py-2.5 font-medium text-sm transition-colors whitespace-nowrap ${
        active
          ? "text-white border-b-2 border-brand-400 font-semibold"
          : "text-gray-400 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-none">
      <div>
        <div className="text-sm font-semibold text-white">{label}</div>
        {description && <div className="text-xs text-ink-400">{description}</div>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`w-11 h-6 flex items-center rounded-full p-1 transition-colors ${
          checked ? "bg-brand-500 justify-end" : "bg-gray-800 justify-start"
        }`}
      >
        <span className="w-4 h-4 bg-white rounded-full shadow-md transform transition-transform" />
      </button>
    </div>
  );
}

