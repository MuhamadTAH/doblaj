import React, { useState } from "react";
import { useUser, useClerk } from "@clerk/clerk-react";
import { useApi, HttpError, AuthFailedError, AuthNetworkError } from "@/hooks/useApi";

export default function SettingsPage() {
  const { user } = useUser();
  const { signOut } = useClerk();
  
  const [password, setPassword] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState("");
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

  return (
    <div className="p-8 max-w-2xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Account Settings</h1>

      <div className="bg-ink-900/20 border border-white/[0.06] rounded-lg p-6 mb-8">
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
  );
}
