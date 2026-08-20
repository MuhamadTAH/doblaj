import React, { useState, useEffect } from "react";
import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";

export const SystemConfigsView: React.FC = () => {
  const flags = useQuery(api.adminQuery.listFeatureFlags);
  const [envStatus, setEnvStatus] = useState<any>(null);
  const [loadingFlag, setLoadingFlag] = useState<string | null>(null);

  const fetchEnvStatus = async () => {
    try {
      const token = localStorage.getItem("clerk-db-jwt") || "";
      const res = await fetch("/api/admin/env-status", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setEnvStatus(data);
    } catch (e) {
      console.error("Env status fetch failed", e);
    }
  };

  useEffect(() => {
    fetchEnvStatus();
  }, []);

  const handleToggleFlag = async (flag: any) => {
    setLoadingFlag(flag.keyName);
    const token = localStorage.getItem("clerk-db-jwt") || "";

    try {
      const res = await fetch(`/api/admin/flags/${flag.keyName}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_active: !flag.isActive, reason: "Admin toggle" }),
      });
      const data = await res.json();
      if (data.status === "APPROVAL_REQUIRED") {
        alert(`Tier 2 Infrastructure Protection: ${data.message}`);
      } else {
        alert(`Flag '${flag.keyName}' updated.`);
      }
    } catch (e: any) {
      alert(`Toggle failed: ${e.message}`);
    } finally {
      setLoadingFlag(null);
    }
  };

  const defaultMasterFlags = [
    { keyName: "RUNPOD_GPU_PROCESSING", tier: "TIER_2_INFRASTRUCTURE", desc: "Master GPU rendering cluster switch" },
    { keyName: "ACCEPT_NEW_JOBS", tier: "TIER_2_INFRASTRUCTURE", desc: "Customer job ingestion gateway" },
    { keyName: "STRIPE_PAYMENT_GATEWAY", tier: "TIER_2_INFRASTRUCTURE", desc: "Billing & credit card purchase pipeline" },
    { keyName: "TELEGRAM_BOT_GLOBAL_GATEWAY", tier: "TIER_2_INFRASTRUCTURE", desc: "Telegram customer AI assistant" },
    { keyName: "ENABLE_FISH_AUDIO_V15", tier: "TIER_1_OPERATIONAL", desc: "Fish Speech 1.5 voice synthesis engine" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">System Configurations & Kill Switches</h1>
        <p className="text-xs text-ink-400">Master infrastructure controls, Tier 2 dual-signoff switches, and cloud service diagnostics</p>
      </div>

      {/* Cloud Integration Status Grid */}
      <div className="p-5 rounded-2xl border border-white/[0.08] bg-ink-900/40 backdrop-blur-xl space-y-4">
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <span>📡 Cloud Integration & Provider Health</span>
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
          {Object.entries(envStatus?.integrations || {
            clerk: true,
            convex: true,
            r2_storage: true,
            runpod_gpu: true,
            fish_audio_tts: true,
            gemini_asr: true,
            telegram_bot: true,
          }).map(([k, v]) => (
            <div key={k} className="p-3 rounded-xl border border-white/[0.06] bg-ink-950/40 flex items-center justify-between">
              <span className="text-ink-300">{k.toUpperCase()}</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${v ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
                {v ? "CONFIGURED" : "MISSING"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Feature Flags Grid */}
      <div className="p-5 rounded-2xl border border-white/[0.08] bg-ink-900/40 backdrop-blur-xl space-y-4">
        <h2 className="text-sm font-bold text-white flex items-center gap-2">
          <span>⚙️ Feature Flags & Master Kill Switches</span>
        </h2>

        <div className="space-y-3">
          {defaultMasterFlags.map((df) => {
            const live = flags?.find((f: any) => f.keyName === df.keyName);
            const isActive = live ? live.isActive : true;
            const isTier2 = df.tier === "TIER_2_INFRASTRUCTURE";

            return (
              <div
                key={df.keyName}
                className="p-4 rounded-xl border border-white/[0.06] bg-ink-950/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4 font-mono text-xs"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{df.keyName}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        isTier2 ? "bg-red-500/20 text-red-300" : "bg-brand-500/20 text-brand-300"
                      }`}
                    >
                      {df.tier}
                    </span>
                  </div>
                  <p className="text-[11px] text-ink-400 mt-1 font-sans">{df.desc}</p>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      isActive ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
                    }`}
                  >
                    {isActive ? "ACTIVE" : "DISABLED"}
                  </span>

                  <button
                    onClick={() => handleToggleFlag({ keyName: df.keyName, isActive })}
                    disabled={loadingFlag === df.keyName}
                    className={`px-4 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider text-white transition-all ${
                      isActive
                        ? "bg-red-600/80 hover:bg-red-500 shadow-sm"
                        : "bg-emerald-600/80 hover:bg-emerald-500 shadow-sm"
                    }`}
                  >
                    {loadingFlag === df.keyName ? "Processing..." : isActive ? "Deactivate" : "Activate"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default SystemConfigsView;
