import React, { useState } from "react";
import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useUser, useAuth } from "@clerk/clerk-react";
import { approveAction, rejectAction } from "../../api/adminApi";

export const PendingApprovalsView: React.FC = () => {
  const approvals = useQuery(api.adminQuery.listPendingApprovals);
  const { user } = useUser();
  const { getToken } = useAuth();

  const [selectedApproval, setSelectedApproval] = useState<any | null>(null);
  const [typedConfirmation, setTypedConfirmation] = useState("");
  const [loading, setLoading] = useState(false);

  const getRequiredConfirmationString = (appr: any) => {
    if (appr.actionType === "REFUND") {
      return `REFUND $${Number(appr.payload?.amountUsd || 0).toFixed(2)}`;
    }
    if (appr.actionType === "CRITICAL_FEATURE_FLAG_TOGGLE") {
      return `TOGGLE ${appr.payload?.flagKey}`;
    }
    return `APPROVE ${appr.actionType}`;
  };

  const handleApprove = async () => {
    if (!selectedApproval) return;
    const requiredStr = getRequiredConfirmationString(selectedApproval);
    if (typedConfirmation !== requiredStr) {
      alert(`Friction Gate: You must type exactly "${requiredStr}" to authorize execution.`);
      return;
    }

    setLoading(true);

    try {
      await approveAction(getToken, selectedApproval._id, "Authorized by second admin with typed verification");
      alert("Action successfully authorized and executed from locked database payload.");
      setSelectedApproval(null);
      setTypedConfirmation("");
    } catch (e: any) {
      alert(`Approval error: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async (approvalId: string) => {
    if (!confirm("Reject and cancel this sensitive action ticket?")) return;

    try {
      await rejectAction(getToken, approvalId, "Rejected by administrator");
      alert("Action request rejected.");
    } catch (e: any) {
      alert(`Rejection error: ${e.message}`);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Pending Dual-Signoff Approvals</h1>
        <p className="text-xs text-ink-400">Anti-tamper multi-party authorization queue for high-value and destructive operations</p>
      </div>

      <div className="space-y-3">
        {(!approvals || approvals.length === 0) && (
          <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 p-12 text-center text-xs text-ink-500 font-mono">
            Zero pending approval tickets. Queue is clear.
          </div>
        )}

        {approvals?.map((appr: any) => {
          const isOwnRequest = appr.requestedBy === user?.id;
          const reqString = getRequiredConfirmationString(appr);

          return (
            <div
              key={appr._id}
              className="p-5 rounded-2xl border border-amber-500/20 bg-amber-500/5 backdrop-blur-xl flex flex-col md:flex-row md:items-center justify-between gap-4 font-mono text-xs"
            >
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300">
                    {appr.actionType}
                  </span>
                  <span className="text-ink-400 text-[11px]">
                    Requested by: <span className="text-white font-semibold">{appr.requestedByEmail || appr.requestedBy}</span>
                  </span>
                </div>

                <div className="text-sm font-bold text-white">
                  Payload: {JSON.stringify(appr.payload)}
                </div>

                {appr.reason && <div className="text-ink-400 text-[11px]">Reason: {appr.reason}</div>}

                {isOwnRequest && (
                  <div className="text-amber-400/90 text-[11px] flex items-center gap-1 font-semibold">
                    🔒 Self-Approval Prohibited: Another administrator must review and sign off.
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => handleReject(appr._id)}
                  className="px-3 py-2 rounded-xl bg-ink-800 hover:bg-ink-700 text-ink-300 text-xs font-semibold"
                >
                  Reject
                </button>

                <button
                  disabled={isOwnRequest}
                  onClick={() => {
                    setSelectedApproval(appr);
                    setTypedConfirmation("");
                  }}
                  className={`px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider text-white shadow-lg transition-all ${
                    isOwnRequest
                      ? "bg-ink-800 text-ink-600 cursor-not-allowed border border-white/5"
                      : "bg-gradient-to-r from-emerald-500 to-emerald-600 hover:brightness-110 shadow-emerald-500/20"
                  }`}
                >
                  {isOwnRequest ? "Locked (Own Request)" : "Review & Authorize"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Cognitive Friction Authorization Modal */}
      {selectedApproval && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
          <div className="max-w-md w-full rounded-2xl border border-emerald-500/30 bg-ink-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <span>🛡️ Authorize High-Impact Action</span>
            </h3>

            <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-xs text-amber-300 space-y-1 font-mono">
              <div className="font-bold">⚠️ BLAST RADIUS REVIEW:</div>
              <div>Action: {selectedApproval.actionType}</div>
              <div>Requester: {selectedApproval.requestedByEmail || selectedApproval.requestedBy}</div>
              <div>Locked Payload: {JSON.stringify(selectedApproval.payload)}</div>
            </div>

            <div className="space-y-2 font-mono text-xs">
              <label className="block text-ink-300">
                To prevent rubber-stamping, type{" "}
                <span className="text-emerald-400 font-bold select-all">
                  {getRequiredConfirmationString(selectedApproval)}
                </span>{" "}
                below:
              </label>
              <input
                type="text"
                value={typedConfirmation}
                onChange={(e) => setTypedConfirmation(e.target.value)}
                placeholder={getRequiredConfirmationString(selectedApproval)}
                className="w-full bg-ink-950 border border-emerald-500/30 rounded-lg p-2.5 text-xs text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setSelectedApproval(null)}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-300 hover:bg-ink-700 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleApprove}
                disabled={loading || typedConfirmation !== getRequiredConfirmationString(selectedApproval)}
                className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider text-white ${
                  typedConfirmation === getRequiredConfirmationString(selectedApproval)
                    ? "bg-emerald-500 hover:bg-emerald-400 shadow-lg shadow-emerald-500/20"
                    : "bg-ink-800 text-ink-500 cursor-not-allowed"
                }`}
              >
                {loading ? "Executing..." : "Sign & Execute"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PendingApprovalsView;
