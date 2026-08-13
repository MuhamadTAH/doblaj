import React, { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useAuth } from "@clerk/clerk-react";
import { secureAuthFetch } from "@/lib/apiClient";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");


interface Transaction {
  legacyId: string;
  createdAt: string;
  amountUsd?: number;
  tier?: string;
}

interface UserData {
  plan?: string;
  remaining_minutes?: number;
  total_minutes?: number;
  used_minutes?: number;
  plan_expiry?: string;
  transactions?: Transaction[];
}

export default function BillingPage() {
  const [userData, setUserData] = useState<UserData | null>(null);
  const { getToken } = useAuth();

  useEffect(() => {
    let isMounted = true;
    
    async function fetchData() {
      try {
        const queryParams = window.location.search;
        const res = await secureAuthFetch(getToken, `${API_BASE}/api/auth/me${queryParams}`);
        const data = await res.json();
        if (isMounted && data.id) {
          setUserData(data);
        }
      } catch (err) {
        console.error("Failed to fetch billing data:", err);
      }
    }
    
    fetchData();
    
    return () => {
      isMounted = false;
    };
  }, [getToken]);

  const isInfinite = userData?.remaining_minutes !== undefined && userData.remaining_minutes >= 100000;
  
  // Calculate expiration date
  const nextBillingDate = userData?.plan_expiry && userData.plan_expiry !== "None" && userData.plan_expiry !== "Unlimited" 
    ? new Date(userData.plan_expiry).toLocaleDateString() 
    : (isInfinite || userData?.plan_expiry === "Unlimited" ? "Unlimited" : "N/A");

  // Real billing history
  const billingHistory = userData?.transactions?.map((tx: any) => ({
    id: tx.transactionId || tx.legacyId || tx._id || "N/A",
    date: tx.createdAt ? new Date(typeof tx.createdAt === 'number' ? tx.createdAt : tx.createdAt).toLocaleDateString() : "N/A",
    amount: tx.amountUsd !== undefined && tx.amountUsd !== null ? `$${Number(tx.amountUsd).toFixed(2)}` : (tx.amount ? `$${tx.amount}` : "$0.00"),
    status: tx.status ? (tx.status.charAt(0).toUpperCase() + tx.status.slice(1)) : "Paid",
    method: "Wayl"
  })) || [];

  return (
    <div className="flex flex-col items-center min-h-[calc(100vh-4rem)] p-6 bg-ink-900/10">
      <div className="max-w-6xl w-full space-y-8 mb-12 flex flex-col">
        
        {/* Header */}
        <div className="text-center md:text-left mt-8 mb-4 flex flex-col md:flex-row justify-between md:items-end">
          <div>
            <motion.h1 
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-4xl md:text-5xl font-extrabold text-white tracking-tight"
            >
              Billing Dashboard
            </motion.h1>
            <motion.p 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="text-lg text-ink-300 mt-2"
            >
              Manage your subscription, usage, and billing history.
            </motion.p>
          </div>
        </div>

        {userData && (
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="grid grid-cols-1 lg:grid-cols-3 gap-6"
          >
            {/* Usage Card */}
            <div className="col-span-1 lg:col-span-2 p-8 rounded-2xl border border-white/5 bg-ink-900/40 backdrop-blur-md shadow-2xl flex flex-col justify-between relative overflow-hidden">
              <div className="absolute top-0 right-0 p-8 opacity-5">
                <svg className="w-48 h-48 text-brand-500" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                </svg>
              </div>
              <div>
                <h3 className="text-xl font-bold text-white mb-2">Usage Overview</h3>
                <p className="text-sm text-ink-400 mb-8">Your dubbing minutes utilization for the current billing cycle.</p>
                
                <div className="space-y-2 relative z-10">
                  <div className="flex justify-between text-sm">
                    <span className="text-ink-200 font-medium">Minutes Remaining</span>
                    <span className="text-white font-bold">{userData.remaining_minutes || 0} min</span>
                  </div>
                  
                  {isInfinite ? (
                    <div className="w-full h-3 bg-ink-800 rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-brand-500 via-accent-500 to-brand-500 w-full rounded-full bg-[length:200%_auto] animate-gradient"></div>
                    </div>
                  ) : (
                    <div className="w-full h-3 bg-ink-800 rounded-full overflow-hidden">
                      <div className="h-full bg-brand-500 rounded-full" style={{ width: userData.total_minutes && userData.total_minutes > 0 ? `${Math.min(100, Math.max(0, ((userData.used_minutes ?? 0) / userData.total_minutes) * 100))}%` : '0%' }}></div>
                    </div>
                  )}
                  
                  <div className="flex justify-between text-xs text-ink-400 mt-2">
                    <span>Used: {userData.used_minutes ?? 0} min</span>
                    <span>Total: {userData.total_minutes ?? userData.remaining_minutes ?? 0} min</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Subscription Card */}
            <div className="col-span-1 p-8 rounded-2xl border border-brand-500/30 bg-brand-500/10 backdrop-blur-md shadow-xl flex flex-col relative overflow-hidden">
              <h3 className="text-xl font-bold text-white mb-6">Current Plan</h3>
              <div className="flex-1 flex flex-col justify-center space-y-6">
                <div>
                  <div className="text-sm text-ink-300 mb-1">Tier</div>
                  <div className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-brand-400 to-accent-400">
                    {userData.plan || (isInfinite ? "Enterprise" : "Free")}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-ink-300 mb-1">Status</div>
                  {userData.remaining_minutes && userData.remaining_minutes > 0 ? (
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500/10 text-green-400 text-sm font-semibold border border-green-500/20">
                      <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></div>
                      Active
                    </div>
                  ) : (
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-500/10 text-red-400 text-sm font-semibold border border-red-500/20">
                      <div className="w-2 h-2 rounded-full bg-red-400"></div>
                      Inactive
                    </div>
                  )}
                </div>
                <div>
                  <div className="text-sm text-ink-300 mb-1">Next Billing Date</div>
                  <div className="text-white font-medium">{nextBillingDate}</div>
                </div>
              </div>
            </div>
            
            {/* Billing History */}
            <div className="col-span-1 lg:col-span-3 mt-4 p-8 rounded-2xl border border-white/5 bg-ink-900/40 backdrop-blur-md shadow-2xl">
              <h3 className="text-xl font-bold text-white mb-6">Billing History</h3>
              {billingHistory.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-ink-300">
                    <thead className="text-xs text-ink-400 uppercase bg-ink-800/50 rounded-t-lg">
                      <tr>
                        <th className="px-6 py-4 font-semibold rounded-tl-lg">Invoice ID</th>
                        <th className="px-6 py-4 font-semibold">Date</th>
                        <th className="px-6 py-4 font-semibold">Amount</th>
                        <th className="px-6 py-4 font-semibold">Method</th>
                        <th className="px-6 py-4 font-semibold text-right rounded-tr-lg">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {billingHistory.map((invoice, idx) => (
                        <tr key={idx} className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
                          <td className="px-6 py-4 font-medium text-white">{invoice.id}</td>
                          <td className="px-6 py-4">{invoice.date}</td>
                          <td className="px-6 py-4">{invoice.amount}</td>
                          <td className="px-6 py-4">{invoice.method}</td>
                          <td className="px-6 py-4 text-right">
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                              {invoice.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-8 text-ink-400">
                  <p>No billing history available.</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}
