import React, { useState } from "react";
import { usePaginatedQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useApi } from "../../hooks/useApi";

export const JobOperationsView: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState("ALL");
  const { results: jobs, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listJobsPaginated,
    { statusFilter },
    { initialNumItems: 50 }
  );

  const [selectedJob, setSelectedJob] = useState<any | null>(null);
  const [actionType, setActionType] = useState<"RETRY" | "FAIL" | "NUKE" | null>(null);
  const [nukeConfirmText, setNukeConfirmText] = useState("");
  const [failReason, setFailReason] = useState("");
  const [overrideProvider, setOverrideProvider] = useState("runpod");
  const [actionLoading, setActionLoading] = useState(false);

  const handleSourceDownload = async (jobId: string) => {
    try {
      const token = localStorage.getItem("clerk-db-jwt") || "";
      const res = await fetch(`/api/admin/jobs/${jobId}/source-download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.download_url) {
        window.open(data.download_url, "_blank");
      } else {
        alert("Download URL not available.");
      }
    } catch (e: any) {
      alert(`Error fetching download URL: ${e.message}`);
    }
  };

  const executeAction = async () => {
    if (!selectedJob) return;
    setActionLoading(true);
    const token = localStorage.getItem("clerk-db-jwt") || "";

    try {
      if (actionType === "RETRY") {
        await fetch(`/api/admin/jobs/${selectedJob._id}/retry`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ override_params: { force_provider: overrideProvider } }),
        });
      } else if (actionType === "FAIL") {
        await fetch(`/api/admin/jobs/${selectedJob._id}/fail`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ reason: failReason || "Marked failed by administrator", refund_minutes: 5 }),
        });
      } else if (actionType === "NUKE") {
        if (nukeConfirmText !== `NUKE ${selectedJob._id}`) {
          alert(`Type confirmation "NUKE ${selectedJob._id}" exactly to unlock.`);
          setActionLoading(false);
          return;
        }
        await fetch(`/api/admin/jobs/${selectedJob._id}/nuke`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ reason: "Purged & banned by administrator" }),
        });
      }

      setActionType(null);
      setSelectedJob(null);
      setNukeConfirmText("");
      setFailReason("");
    } catch (e: any) {
      alert(`Operation failed: ${e.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header & Filter Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Job Operations Center</h1>
          <p className="text-xs text-ink-400">Global pipeline inspection, DLQ rescue, and emergency nuke operations</p>
        </div>

        <div className="flex items-center gap-1.5 bg-ink-900/60 p-1 rounded-xl border border-white/[0.06] overflow-x-auto">
          {["ALL", "DEAD_LETTER", "QUEUED", "PROCESSING", "FAILED", "COMPLETED"].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                statusFilter === st
                  ? "bg-brand-500/20 text-brand-300 border border-brand-500/30"
                  : "text-ink-400 hover:text-white"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Jobs Table */}
      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/[0.08] bg-ink-950/60 text-[11px] uppercase tracking-wider text-ink-400 font-mono">
              <tr>
                <th className="py-3.5 px-4">Job ID / Legacy</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Retries</th>
                <th className="py-3.5 px-4">Language / TTS</th>
                <th className="py-3.5 px-4">API Cost</th>
                <th className="py-3.5 px-4">Created</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200">
              {jobs.map((job) => (
                <tr key={job._id} className="hover:bg-white/[0.02] transition-colors font-mono">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white truncate max-w-[140px]">{job._id}</div>
                    <div className="text-[10px] text-ink-500 truncate max-w-[140px]">{job.legacyId}</div>
                  </td>
                  <td className="py-3 px-4">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        job.status === "DEAD_LETTER"
                          ? "bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse"
                          : job.status === "COMPLETED"
                          ? "bg-emerald-500/15 text-emerald-400"
                          : job.status === "PROCESSING"
                          ? "bg-brand-500/20 text-brand-300"
                          : "bg-amber-500/15 text-amber-300"
                      }`}
                    >
                      {job.status}
                    </span>
                    {job.failedStep && (
                      <div className="text-[10px] text-red-400/80 mt-1">Step: {job.failedStep}</div>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    <span className={job.retry_count && job.retry_count >= 3 ? "text-red-400 font-bold" : "text-ink-400"}>
                      {job.retry_count ?? 0} / {job.max_retries ?? 3}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-ink-300">
                    <div>{job.sourceLang} ➔ {job.targetLang}</div>
                    <div className="text-[10px] text-ink-500">{job.ttsProvider}</div>
                  </td>
                  <td className="py-3 px-4 text-purple-300 font-semibold">
                    ${(job.total_cost_usd ?? job.api_cost ?? 0).toFixed(3)}
                  </td>
                  <td className="py-3 px-4 text-ink-500 text-[11px]">
                    {new Date(job.createdAt || job._creationTime).toLocaleString()}
                  </td>
                  <td className="py-3 px-4 text-right space-x-1.5">
                    <button
                      onClick={() => handleSourceDownload(job._id)}
                      title="Download Input Video/Audio"
                      className="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-ink-300 text-[11px]"
                    >
                      📥 Raw
                    </button>
                    <button
                      onClick={() => {
                        setSelectedJob(job);
                        setActionType("RETRY");
                      }}
                      className="px-2 py-1 rounded bg-brand-500/15 hover:bg-brand-500/25 text-brand-300 text-[11px]"
                    >
                      🔄 Retry
                    </button>
                    <button
                      onClick={() => {
                        setSelectedJob(job);
                        setActionType("FAIL");
                      }}
                      className="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-[11px]"
                    >
                      ⚠️ Fail
                    </button>
                    <button
                      onClick={() => {
                        setSelectedJob(job);
                        setActionType("NUKE");
                      }}
                      className="px-2 py-1 rounded bg-red-500/15 hover:bg-red-500/25 text-red-400 text-[11px] font-bold"
                    >
                      💥 Nuke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Load More Pagination */}
        {status === "CanLoadMore" && (
          <div className="p-4 border-t border-white/[0.06] text-center">
            <button
              onClick={() => loadMore(50)}
              disabled={isLoading}
              className="px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-xs font-mono font-semibold text-ink-200 transition-colors"
            >
              {isLoading ? "Loading..." : "Load 50 More Jobs"}
            </button>
          </div>
        )}
      </div>

      {/* Modal Dialog for Actions */}
      {actionType && selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
          <div className="max-w-md w-full rounded-2xl border border-white/10 bg-ink-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              {actionType === "RETRY" && "🔄 Force Retry Job"}
              {actionType === "FAIL" && "⚠️ Mark Job as Failed & Issue Refund"}
              {actionType === "NUKE" && "💥 Poison Pill Nuke & Ban"}
            </h3>

            <p className="text-xs text-ink-400 font-mono">
              Target Job ID: <span className="text-white">{selectedJob._id}</span>
            </p>

            {actionType === "RETRY" && (
              <div className="space-y-3">
                <label className="block text-xs text-ink-300 font-medium">Provider Override:</label>
                <select
                  value={overrideProvider}
                  onChange={(e) => setOverrideProvider(e.target.value)}
                  className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
                >
                  <option value="runpod">RunPod GPU Serverless</option>
                  <option value="gemini">Gemini Direct 3.1 Pro</option>
                  <option value="fish_audio">Fish Audio Cloud</option>
                </select>
              </div>
            )}

            {actionType === "FAIL" && (
              <div className="space-y-3">
                <label className="block text-xs text-ink-300 font-medium">Failure Reason:</label>
                <input
                  type="text"
                  placeholder="e.g. Unrecoverable audio corruption"
                  value={failReason}
                  onChange={(e) => setFailReason(e.target.value)}
                  className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
                />
              </div>
            )}

            {actionType === "NUKE" && (
              <div className="space-y-3">
                <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-xs text-red-300 font-mono">
                  ⚠️ BLAST RADIUS: This will permanently delete R2 audio/video files, mark the job CANCELLED_PURGED, ban the user, and terminate all active user sessions.
                </div>
                <label className="block text-xs text-ink-300">
                  Type <span className="text-red-400 font-mono font-bold">NUKE {selectedJob._id}</span> to confirm:
                </label>
                <input
                  type="text"
                  value={nukeConfirmText}
                  onChange={(e) => setNukeConfirmText(e.target.value)}
                  placeholder={`NUKE ${selectedJob._id}`}
                  className="w-full bg-ink-950 border border-red-500/30 rounded-lg p-2 text-xs font-mono text-white"
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setActionType(null)}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-300 hover:bg-ink-700 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={executeAction}
                disabled={actionLoading}
                className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider text-white ${
                  actionType === "NUKE"
                    ? "bg-red-600 hover:bg-red-500"
                    : "bg-brand-500 hover:bg-brand-400"
                }`}
              >
                {actionLoading ? "Executing..." : "Confirm Action"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default JobOperationsView;
