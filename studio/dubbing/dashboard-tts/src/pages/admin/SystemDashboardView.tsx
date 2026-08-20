import React from "react";
import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";

export const SystemDashboardView: React.FC = () => {
  const metrics = useQuery(api.adminQuery.getAdminMetrics);
  const outboxHealth = useQuery(api.admin.getOutboxHealthQuery);

  return (
    <div className="space-y-6">
      {/* Top Banner / Pipeline Health */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-2xl border border-white/[0.08] bg-gradient-to-r from-ink-900/80 to-ink-900/40 backdrop-blur-xl">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">System Command Center</h1>
          <p className="text-xs text-ink-400 mt-0.5">Real-time pipeline telemetry, burn rate, and operational health</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>FastAPI & GPU Pipeline: ONLINE</span>
          </div>

          <div
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono ${
              outboxHealth?.isHealthy
                ? "bg-brand-500/10 border-brand-500/20 text-brand-300"
                : "bg-red-500/10 border-red-500/20 text-red-400"
            }`}
          >
            <span>SIEM Outbox: {outboxHealth?.pendingCount ?? 0} PENDING</span>
          </div>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
        <div className="p-4 rounded-xl border border-white/[0.06] bg-ink-900/50">
          <span className="text-[11px] uppercase tracking-wider text-ink-400 font-medium font-mono">Processing</span>
          <div className="text-2xl font-bold text-brand-300 mt-1 font-mono">{metrics?.activeJobs ?? 0}</div>
          <span className="text-[10px] text-ink-500">Active GPU/CPU renders</span>
        </div>

        <div className="p-4 rounded-xl border border-white/[0.06] bg-ink-900/50">
          <span className="text-[11px] uppercase tracking-wider text-ink-400 font-medium font-mono">Queued</span>
          <div className="text-2xl font-bold text-amber-400 mt-1 font-mono">{metrics?.queuedJobs ?? 0}</div>
          <span className="text-[10px] text-ink-500">Pending worker pickup</span>
        </div>

        <div className="p-4 rounded-xl border border-red-500/20 bg-red-500/5">
          <span className="text-[11px] uppercase tracking-wider text-red-400 font-medium font-mono">Dead Letter (DLQ)</span>
          <div className="text-2xl font-bold text-red-400 mt-1 font-mono">{metrics?.deadLetterJobs ?? 0}</div>
          <span className="text-[10px] text-red-500/80">Max retries exceeded</span>
        </div>

        <div className="p-4 rounded-xl border border-white/[0.06] bg-ink-900/50">
          <span className="text-[11px] uppercase tracking-wider text-ink-400 font-medium font-mono">Completed</span>
          <div className="text-2xl font-bold text-emerald-400 mt-1 font-mono">{metrics?.completedJobs ?? 0}</div>
          <span className="text-[10px] text-ink-500">Master renders ready</span>
        </div>

        <div className="p-4 rounded-xl border border-white/[0.06] bg-ink-900/50">
          <span className="text-[11px] uppercase tracking-wider text-ink-400 font-medium font-mono">Est. 24h API Burn</span>
          <div className="text-2xl font-bold text-purple-300 mt-1 font-mono">
            ${metrics?.estimatedApiCostUsd24h?.toFixed(2) ?? "0.00"}
          </div>
          <span className="text-[10px] text-ink-500">RunPod + Gemini + Fish</span>
        </div>

        <div className="p-4 rounded-xl border border-amber-500/20 bg-amber-500/5">
          <span className="text-[11px] uppercase tracking-wider text-amber-400 font-medium font-mono">Pending Approvals</span>
          <div className="text-2xl font-bold text-amber-300 mt-1 font-mono">{metrics?.pendingApprovalsCount ?? 0}</div>
          <span className="text-[10px] text-amber-500/80">Dual signoff required</span>
        </div>
      </div>

      {/* Security Alerts & System Feed */}
      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 p-5 backdrop-blur-xl">
        <h2 className="text-sm font-bold text-white tracking-tight flex items-center gap-2 mb-4">
          <span>🚨 Live Security & Operational Feed</span>
        </h2>

        <div className="space-y-2">
          {(!metrics?.recentAlerts || metrics.recentAlerts.length === 0) && (
            <div className="py-8 text-center text-xs text-ink-500 font-mono">
              Zero active security alerts. Pipeline is healthy.
            </div>
          )}

          {metrics?.recentAlerts?.map((alt: any) => (
            <div
              key={alt._id}
              className="p-3 rounded-lg border border-red-500/20 bg-red-500/5 flex items-center justify-between text-xs"
            >
              <div className="flex items-center gap-2.5">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-red-500/20 text-red-300">
                  {alt.type}
                </span>
                <span className="text-ink-200 font-mono">{alt.referenceId || "GLOBAL"}</span>
                <span className="text-ink-400">{JSON.stringify(alt.details || {})}</span>
              </div>
              <span className="text-[11px] text-ink-500 font-mono">
                {new Date(alt.createdAt).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default SystemDashboardView;
