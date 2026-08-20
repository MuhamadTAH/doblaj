import React, { useState } from "react";
import { usePaginatedQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { adminFetch } from "../../api/adminApi";

export const FinancialLedgerView: React.FC = () => {
  const { getToken } = useAuth();
  const { results: transactions, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listTransactionsPaginated,
    {},
    { initialNumItems: 50 }
  );

  const [refundTx, setRefundTx] = useState<any | null>(null);
  const [refundAmount, setRefundAmount] = useState<number>(10.0);
  const [refundReason, setRefundReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleRefundSubmit = async () => {
    if (!refundTx) return;
    setLoading(true);
    setFeedback(null);

    try {
      const res = await adminFetch(getToken, `/api/admin/transactions/${refundTx._id}/refund`, {
        method: "POST",
        body: JSON.stringify({
          amount_usd: refundAmount,
          reason: refundReason || "Customer support refund",
        }),
      });
      const data = await res.json();
      if (data.status === "APPROVAL_REQUIRED") {
        setFeedback(data.message);
      } else {
        alert(data.message || "Refund processed.");
        setRefundTx(null);
      }
    } catch (e: any) {
      alert(`Refund request failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Financial Ledger (The Books)</h1>
        <p className="text-xs text-ink-400">Append-only transaction feed, deposit logs, and dual-signoff refund gating</p>
      </div>

      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/[0.08] bg-ink-950/60 text-[11px] uppercase tracking-wider text-ink-400 font-mono">
              <tr>
                <th className="py-3.5 px-4">Transaction Reference</th>
                <th className="py-3.5 px-4">Tier / Package</th>
                <th className="py-3.5 px-4">Amount</th>
                <th className="py-3.5 px-4">Minutes Granted</th>
                <th className="py-3.5 px-4">Status</th>
                <th className="py-3.5 px-4">Timestamp</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200 font-mono">
              {transactions.map((tx: any) => (
                <tr key={tx._id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-semibold text-white">{tx.referenceId || tx._id}</div>
                    <div className="text-[10px] text-ink-500">{tx.subyTransactionId || "STRIPE / SUBY"}</div>
                  </td>
                  <td className="py-3 px-4 uppercase text-brand-300 font-semibold">{tx.tier || "Standard"}</td>
                  <td className="py-3 px-4 text-emerald-300 font-bold">
                    ${(tx.amountUsd ?? (tx.amount ? tx.amount / 100 : 0)).toFixed(2)} {tx.currency || "USD"}
                  </td>
                  <td className="py-3 px-4 text-white font-semibold">+{tx.minutesAdded ?? 0} min</td>
                  <td className="py-3 px-4">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        tx.status === "refunded"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-emerald-500/15 text-emerald-400"
                      }`}
                    >
                      {tx.status || "COMPLETE"}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-ink-500 text-[11px]">
                    {new Date(tx.createdAt || tx._creationTime).toLocaleString()}
                  </td>
                  <td className="py-3 px-4 text-right">
                    {tx.status !== "refunded" && (
                      <button
                        onClick={() => {
                          setRefundTx(tx);
                          setRefundAmount(tx.amountUsd ?? (tx.amount ? tx.amount / 100 : 10));
                          setFeedback(null);
                        }}
                        className="px-2.5 py-1 rounded bg-red-500/15 hover:bg-red-500/25 text-red-400 text-[11px] font-bold"
                      >
                        Refund
                      </button>
                    )}
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
              {isLoading ? "Loading..." : "Load 50 More Transactions"}
            </button>
          </div>
        )}
      </div>

      {/* Refund Modal */}
      {refundTx && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
          <div className="max-w-md w-full rounded-2xl border border-white/10 bg-ink-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <span>💳 Issue Customer Refund</span>
            </h3>

            <p className="text-xs text-ink-400 font-mono">
              Target Ref: <span className="text-white">{refundTx.referenceId || refundTx._id}</span>
            </p>

            <div className="space-y-3">
              <label className="block text-xs text-ink-300 font-medium">Refund Amount (USD):</label>
              <input
                type="number"
                step="0.01"
                value={refundAmount}
                onChange={(e) => setRefundAmount(parseFloat(e.target.value) || 0)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-sm font-mono text-white"
              />

              {refundAmount > 50 && (
                <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 text-xs text-amber-300 font-mono">
                  ⚠️ Amounts over $50.00 will automatically route to the Dual-Signoff Pending Approvals Queue.
                </div>
              )}

              <label className="block text-xs text-ink-300 font-medium">Reason:</label>
              <input
                type="text"
                placeholder="e.g. Unused credits refund requested by user"
                value={refundReason}
                onChange={(e) => setRefundReason(e.target.value)}
                className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
              />
            </div>

            {feedback && (
              <div className="p-3 rounded-lg border border-brand-500/30 bg-brand-500/10 text-xs text-brand-300 font-mono">
                {feedback}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setRefundTx(null)}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-300 hover:bg-ink-700 text-xs"
              >
                Close
              </button>
              <button
                onClick={handleRefundSubmit}
                disabled={loading}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-xs font-bold uppercase tracking-wider text-white"
              >
                {loading ? "Processing..." : refundAmount > 50 ? "Request Approval" : "Execute Refund"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default FinancialLedgerView;
