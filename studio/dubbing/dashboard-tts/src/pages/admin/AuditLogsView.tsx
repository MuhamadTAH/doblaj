import React, { useState } from "react";
import { usePaginatedQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";

export const AuditLogsView: React.FC = () => {
  const [targetFilter, setTargetFilter] = useState("ALL");
  const { results: logs, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listAuditLogsPaginated,
    { targetFilter },
    { initialNumItems: 50 }
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Audit Logs & Diff Inspection</h1>
          <p className="text-xs text-ink-400">Immutable forensic audit trail with compact delta diffs and SIEM outbox sync</p>
        </div>

        <div className="flex items-center gap-1.5 bg-ink-900/60 p-1 rounded-xl border border-white/[0.06] overflow-x-auto">
          {["ALL", "users", "dubbingJobs", "workspaces", "featureFlags", "actionApprovals"].map((res) => (
            <button
              key={res}
              onClick={() => setTargetFilter(res)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                targetFilter === res
                  ? "bg-brand-500/20 text-brand-300 border border-brand-500/30"
                  : "text-ink-400 hover:text-white"
              }`}
            >
              {res}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="border-b border-white/[0.08] bg-ink-950/60 text-[11px] uppercase tracking-wider text-ink-400">
              <tr>
                <th className="py-3.5 px-4">Timestamp</th>
                <th className="py-3.5 px-4">Actor</th>
                <th className="py-3.5 px-4">Action</th>
                <th className="py-3.5 px-4">Target Resource</th>
                <th className="py-3.5 px-4">Changed Fields (Delta Diff)</th>
                <th className="py-3.5 px-4">Metadata</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200">
              {logs.map((log: any) => (
                <tr key={log._id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="py-3 px-4 text-ink-400 text-[11px] whitespace-nowrap">
                    {new Date(log.createdAt || log._creationTime).toLocaleString()}
                  </td>
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white">{log.actorEmail || log.actorId}</div>
                    {log.metadata?.impersonatorId && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-bold">
                        IMPERSONATING
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-brand-500/15 text-brand-300">
                      {log.action}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-ink-300">
                    <div>{log.targetResource}</div>
                    <div className="text-[10px] text-ink-500">{log.targetId}</div>
                  </td>
                  <td className="py-3 px-4">
                    {log.changedFields ? (
                      <div className="space-y-1">
                        {Object.entries(log.changedFields).map(([k, v]: [string, any]) => (
                          <div key={k} className="flex items-center gap-1.5 text-[11px]">
                            <span className="text-ink-400">{k}:</span>
                            <span className="px-1.5 py-0.2 rounded bg-red-500/10 text-red-300 line-through">
                              {JSON.stringify(v.old ?? "null")}
                            </span>
                            <span>➔</span>
                            <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-300 font-semibold">
                              {JSON.stringify(v.new ?? "null")}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-ink-600 text-[10px]">No field mutations</span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-ink-500 text-[10px] max-w-[200px] truncate">
                    {JSON.stringify(log.metadata || {})}
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
              {isLoading ? "Loading..." : "Load 50 More Logs"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default AuditLogsView;
