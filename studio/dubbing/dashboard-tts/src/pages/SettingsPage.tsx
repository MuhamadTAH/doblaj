import React, { useState } from "react";
import { useUser, useClerk } from "@clerk/clerk-react";
import { useApi, HttpError, AuthFailedError, AuthNetworkError } from "@/hooks/useApi";

export default function SettingsPage() {
  const { user } = useUser();
  const { signOut } = useClerk();
  
  const [activeTab, setActiveTab] = useState<"general" | "connections">("general");
  const [password, setPassword] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState("");
  
  const [isConnecting, setIsConnecting] = useState(false);
  const [telegramError, setTelegramError] = useState("");
  
  const api = useApi();

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

  return (
    <div className="p-8 max-w-2xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Account Settings</h1>

      <div className="flex border-b border-gray-800 mb-8">
        <button
          onClick={() => setActiveTab("general")}
          className={`px-4 py-2 font-medium text-sm transition-colors ${
            activeTab === "general"
              ? "text-white border-b-2 border-primary-500"
              : "text-gray-400 hover:text-white"
          }`}
        >
          General
        </button>
        <button
          onClick={() => setActiveTab("connections")}
          className={`px-4 py-2 font-medium text-sm transition-colors ${
            activeTab === "connections"
              ? "text-white border-b-2 border-primary-500"
              : "text-gray-400 hover:text-white"
          }`}
        >
          Connections
        </button>
      </div>

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
