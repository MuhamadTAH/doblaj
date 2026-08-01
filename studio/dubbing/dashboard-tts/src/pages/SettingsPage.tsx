import React, { useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");


export default function SettingsPage() {
  const [password, setPassword] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState("");

  const handleDelete = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsDeleting(true);
    setMessage("");

    try {
      // Pird: rely on the HttpOnly dubbing_access_token cookie via
      // credentials: "include". Do NOT read the cookie from JavaScript
      // — HttpOnly cookies are invisible to document.cookie, and exposing
      // a non-HttpOnly token to JS would let any XSS steal the session.
      const res = await fetch(`${API_BASE}/api/user/delete`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ password }),
      });

      if (res.ok) {
        setMessage("Your account has been queued for deletion.");
        setTimeout(() => {
          window.location.href = "/";
        }, 2000);
      } else {
        const data = await res.json();
        setMessage(data.detail || "Failed to delete account.");
      }
    } catch (err) {
      setMessage("Error communicating with the server.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="p-8 max-w-2xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Account Settings</h1>

      <div className="border border-red-500 rounded-lg p-6 bg-red-900/20">
        <h2 className="text-xl font-bold text-red-500 mb-2">Delete My Data</h2>
        <p className="text-red-300 mb-4">
          This action is permanent and cannot be undone. All your voice models, generated audio, and video projects will be deleted. Some transactional records may be retained for legal compliance.
        </p>

        {message && (
          <div className="mb-4 p-3 bg-red-900/50 text-red-200 rounded">
            {message}
          </div>
        )}

        <form onSubmit={handleDelete} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Confirm Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
              required
            />
          </div>
          <button
            type="submit"
            disabled={isDeleting}
            className="bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded w-max"
          >
            {isDeleting ? "Deleting..." : "Permanently Delete Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
