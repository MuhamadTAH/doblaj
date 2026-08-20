import React, { useState } from "react";
import { usePaginatedQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";

export const UserIntelligenceView: React.FC = () => {
  const { results: users, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listUsersPaginated,
    {},
    { initialNumItems: 50 }
  );

  const [selectedUser, setSelectedUser] = useState<any | null>(null);
  const [balanceDelta, setBalanceDelta] = useState<number>(10);
  const [adjustReason, setAdjustReason] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleAdjustBalance = async () => {
    if (!selectedUser) return;
    setLoading(true);
    const token = localStorage.getItem("clerk-db-jwt") || "";

    try {
      await fetch(`/api/admin/users/${selectedUser.clerkId}/balance`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          delta_minutes: balanceDelta,
          reason: adjustReason || "Support credit grant",
        }),
      });
      setModalOpen(false);
      setSelectedUser(null);
      setAdjustReason("");
    } catch (e: any) {
      alert(`Balance adjustment failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleImpersonate = async (user: any) => {
    if (!confirm(`Generate impersonation session for ${user.email}? All actions will be signed with your admin audit ID.`)) {
      return;
    }
    const token = localStorage.getItem("clerk-db-jwt") || "";

    try {
      const res = await fetch(`/api/admin/users/${user.clerkId}/impersonate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.impersonation_token) {
        localStorage.setItem("clerk-db-jwt", data.impersonation_token);
        localStorage.setItem("is_impersonating", "true");
        localStorage.setItem("impersonated_email", data.target_email);
        window.location.href = "/tts";
      }
    } catch (e: any) {
      alert(`Impersonation failed: ${e.message}`);
    }
  };

  const handleToggleBan = async (user: any) => {
    const isBanning = !user.isBanned;
    if (!confirm(`${isBanning ? "Ban" : "Unban"} user ${user.email}?`)) return;
    const token = localStorage.getItem("clerk-db-jwt") || "";

    try {
      await fetch(`/api/admin/users/${user.clerkId}/ban`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_banned: isBanning, reason: "Admin CRM action" }),
      });
    } catch (e: any) {
      alert(`Ban toggle failed: ${e.message}`);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">User Intelligence (CRM)</h1>
        <p className="text-xs text-ink-400">Searchable accounts directory, balance governance, and impersonation tooling</p>
      </div>

      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/[0.08] bg-ink-950/60 text-[11px] uppercase tracking-wider text-ink-400 font-mono">
              <tr>
                <th className="py-3.5 px-4">User / Clerk ID</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Plan</th>
                <th className="py-3.5 px-4">Minutes Balance</th>
                <th className="py-3.5 px-4">Updated</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200 font-mono">
              {users.map((u: any) => (
                <tr key={u._id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white">{u.email || "No Email"}</div>
                    <div className="text-[10px] text-ink-500 truncate max-w-[160px]">{u.clerkId}</div>
                  </td>
                  <td className="py-3 px-4">
                    {u.isBanned ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/20 text-red-400">
                        BANNED
                      </span>
                    ) : u.deletedAt ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-400">
                        SOFT-DELETED
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400">
                        ACTIVE
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 uppercase text-[11px] font-semibold text-brand-300">
                    {u.workspacePlan || "FREE"}
                  </td>
                  <td className="py-3 px-4">
                    <span className="text-white font-bold text-sm">{u.dubbingMinutes ?? 0}</span>
                    <span className="text-ink-500 text-[10px] ml-1">min</span>
                  </td>
                  <td className="py-3 px-4 text-ink-500 text-[11px]">
                    {new Date(u.updatedAt || u._creationTime).toLocaleDateString()}
                  </td>
                  <td className="py-3 px-4 text-right space-x-1.5">
                    <button
                      onClick={() => {
                        setSelectedUser(u);
                        setModalOpen(true);
                      }}
                      className="px-2 py-1 rounded bg-brand-500/15 hover:bg-brand-500/25 text-brand-300 text-[11px]"
                    >
                      ⚖️ Balance
                    </button>
                    <button
                      onClick={() => handleImpersonate(u)}
                      title="Impersonate User with full SIEM audit trace"
                      className="px-2 py-1 rounded bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 text-[11px]"
                    >
                      🎭 Impersonate
                    </button>
                    <button
                      onClick={() => handleToggleBan(u)}
                      className={`px-2 py-1 rounded text-[11px] font-bold ${
                        u.isBanned
                          ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                          : "bg-red-500/15 text-red-400 hover:bg-red-500/25"
                      }`}
                    >
                      {u.isBanned ? "Unban" : "Ban"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {status === "CanLoadMore" && (
          <div className="p-4 border-t border-white/[0.06] text-center">
            <button
              onClick={() => loadMore(50)}
              disabled={isLoading}
              className="px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-xs font-mono font-semibold text-ink-200"
            >
              {isLoading ? "Loading..." : "Load 50 More Users"}
            </button>
          </div>
        )}
      </div>

      {/* Balance Adjust Modal */}
      {modalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
          <div className="max-w-md w-full rounded-2xl border border-white/10 bg-ink-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white">⚖️ Adjust Minutes Balance</h3>
            <p className="text-xs text-ink-400 font-mono">
              Target User: <span className="text-white">{selectedUser.email}</span>
            </p>

            <div className="space-y-3">
              <label className="block text-xs text-ink-300 font-medium">Minutes Delta (positive or negative):</label>
              <input
                type="number"
                value={balanceDelta}
                onChange={(e) => setBalanceDelta(parseInt(e.target.value) || 0)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-sm font-mono text-white"
              />

              <label className="block text-xs text-ink-300 font-medium">Reason for Audit Log:</label>
              <input
                type="text"
                placeholder="e.g. VIP promotion bonus"
                value={adjustReason}
                onChange={(e) => setAdjustReason(e.target.value)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-300 hover:bg-ink-700 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleAdjustBalance}
                disabled={loading}
                className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-bold uppercase tracking-wider text-white"
              >
                {loading ? "Updating..." : "Commit Balance"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserIntelligenceView;
