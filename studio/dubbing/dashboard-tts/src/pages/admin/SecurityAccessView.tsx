import React, { useState } from "react";
import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { adminFetch } from "../../api/adminApi";

export const SecurityAccessView: React.FC = () => {
  const rbacData = useQuery(api.adminQuery.listAdminRoles);
  const { getToken } = useAuth();
  const [targetUserId, setTargetUserId] = useState("");
  const [selectedRole, setSelectedRole] = useState("Pipeline Operator");
  const [loading, setLoading] = useState(false);

  const handleAssignRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUserId) return;
    setLoading(true);

    try {
      await adminFetch(getToken, "/api/admin/roles/assign", {
        method: "POST",
        body: JSON.stringify({
          user_id: targetUserId,
          role_name: selectedRole,
          permissions: ["dubbing:read", "dubbing:write"],
        }),
      });
      alert(`Role ${selectedRole} assigned to ${targetUserId}. Synced to Clerk.`);
      setTargetUserId("");
    } catch (e: any) {
      alert(`Role assignment failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRevokeSessions = async (userId: string) => {
    if (!confirm(`Revoke all active Clerk sessions for user ${userId}?`)) return;

    try {
      await adminFetch(getToken, `/api/admin/users/${userId}/ban`, {
        method: "POST",
        body: JSON.stringify({ reason: "Manual admin session revocation and ban" }),
      });
      alert(`All active sessions revoked for ${userId}.`);
    } catch (e: any) {
      alert(`Session revocation failed: ${e.message}`);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Security & Access Control (The Bouncer)</h1>
        <p className="text-xs text-ink-400">Relational RBAC permissions matrix, admin user roster, and instant session revocation</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Assign Role Form */}
        <div className="p-5 rounded-2xl border border-white/[0.08] bg-ink-900/40 backdrop-blur-xl space-y-4">
          <h2 className="text-sm font-bold text-white flex items-center gap-2">
            <span>🛡️ Assign Role to User</span>
          </h2>

          <form onSubmit={handleAssignRole} className="space-y-3 font-mono text-xs">
            <div>
              <label className="block text-ink-400 mb-1">Clerk User ID:</label>
              <input
                type="text"
                placeholder="user_2..."
                value={targetUserId}
                onChange={(e) => setTargetUserId(e.target.value)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-white placeholder:text-ink-600"
              />
            </div>

            <div>
              <label className="block text-ink-400 mb-1">Role Container:</label>
              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-white"
              >
                <option value="Super Admin">Super Admin (admin:all)</option>
                <option value="Financial Controller">Financial Controller (billing:manage)</option>
                <option value="Pipeline Operator">Pipeline Operator (dubbing:write)</option>
                <option value="Tier 1 Support">Tier 1 Support (dubbing:read)</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={loading || !targetUserId}
              className="w-full py-2.5 rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-bold tracking-wider uppercase text-[11px] transition-colors"
            >
              {loading ? "Syncing..." : "Assign Role (Sync Clerk)"}
            </button>
          </form>
        </div>

        {/* Permissions Grid */}
        <div className="lg:col-span-2 p-5 rounded-2xl border border-white/[0.08] bg-ink-900/40 backdrop-blur-xl">
          <h2 className="text-sm font-bold text-white flex items-center gap-2 mb-4">
            <span>🔐 Active RBAC Permission Strings</span>
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono">
            {[
              { perm: "admin:all", desc: "Unrestricted master operational capabilities" },
              { perm: "billing:manage", desc: "Execute and review financial refunds & balances" },
              { perm: "dubbing:write", desc: "Trigger retries, pipeline overrides, and chunk fixes" },
              { perm: "dubbing:read", desc: "Read telemetry, audit logs, and download source audio" },
              { perm: "users:impersonate", desc: "Generate auditable impersonation sessions" },
              { perm: "jobs:nuke", desc: "Purge R2 objects and ban malicious actors" },
            ].map((p) => (
              <div key={p.perm} className="p-3 rounded-lg border border-white/[0.06] bg-ink-950/40 space-y-1">
                <div className="font-bold text-brand-300">{p.perm}</div>
                <div className="text-[11px] text-ink-400">{p.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Admin User Roster */}
      <div className="p-5 rounded-2xl border border-white/[0.08] bg-ink-900/40 backdrop-blur-xl">
        <h2 className="text-sm font-bold text-white flex items-center gap-2 mb-4">
          <span>👥 Admin Roster & Active Sessions</span>
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="border-b border-white/[0.08] text-[11px] uppercase tracking-wider text-ink-400">
              <tr>
                <th className="py-2.5 px-3">User ID</th>
                <th className="py-2.5 px-3">Elevated Role</th>
                <th className="py-2.5 px-3">Assigned By</th>
                <th className="py-2.5 px-3 text-right">Emergency Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200">
              {(rbacData?.userRoles || []).map((ur: any) => (
                <tr key={ur._id}>
                  <td className="py-2.5 px-3 font-semibold text-white">{ur.userId}</td>
                  <td className="py-2.5 px-3 text-brand-300">Super Admin</td>
                  <td className="py-2.5 px-3 text-ink-500">{ur.assignedBy || "SYSTEM_BOOTSTRAP"}</td>
                  <td className="py-2.5 px-3 text-right">
                    <button
                      onClick={() => handleRevokeSessions(ur.userId)}
                      className="px-2.5 py-1 rounded bg-red-500/15 hover:bg-red-500/25 text-red-400 text-[10px] font-bold uppercase tracking-wider"
                    >
                      Revoke Sessions
                    </button>
                  </td>
                </tr>
              ))}
              {(!rbacData?.userRoles || rbacData.userRoles.length === 0) && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-ink-500 text-xs">
                    Root bootstrap active via Clerk Organization Admin Claims.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default SecurityAccessView;
