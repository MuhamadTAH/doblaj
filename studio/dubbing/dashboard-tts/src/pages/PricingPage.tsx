import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import PricingCard from "@/components/PricingCard";
import { useAuth } from "@clerk/clerk-react";
import { useSearchParams } from "react-router-dom";
import { secureAuthFetch } from "@/lib/apiClient";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export default function PricingPage() {
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [userData, setUserData] = useState<any>(null);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const { getToken } = useAuth();
  const [searchParams] = useSearchParams();
  const hasTriggeredCheckout = useRef(false);

  // Fetch user plan and details
  useEffect(() => {
    async function fetchUserPlan() {
      try {
        const res = await secureAuthFetch(getToken, `${API_BASE}/api/auth/me`);
        if (res.ok) {
          const data = await res.json();
          setUserData(data);
          setCurrentPlan(data?.plan?.toLowerCase() || null);
        }
      } catch (err) {
        console.error("Failed to fetch user plan", err);
      }
    }
    fetchUserPlan();
  }, [getToken]);

  // Handle post-payment redirect query params (e.g., ?payment=success)
  useEffect(() => {
    const paymentStatus = searchParams.get("payment");
    if (paymentStatus === "success") {
      setNotification({
        type: 'success',
        message: "Payment successful! Your workspace balance is updating..."
      });
      // Clean up URL query parameters without reloading
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (paymentStatus === "cancel" || paymentStatus === "failed") {
      setNotification({
        type: 'error',
        message: "Payment was cancelled or failed. Please try again."
      });
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    const plan = searchParams.get("plan");
    if (plan && !hasTriggeredCheckout.current) {
      hasTriggeredCheckout.current = true;
      window.history.replaceState({}, document.title, window.location.pathname);
      handleCheckout(plan);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const handleCheckout = async (tierId: string) => {
    setLoadingTier(tierId);
    setNotification(null);

    try {
      const res = await secureAuthFetch(getToken, `${API_BASE}/api/payments/checkout`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ tier: tierId })
      });

      const data = await res.json().catch(() => {
        throw new Error("Invalid response format from server");
      });


      if (data.checkoutUrl) {
        // Redirect to Wayl checkout URL
        window.location.href = data.checkoutUrl;
      } else {
        throw new Error("Missing checkout URL in server response");
      }
    } catch (err: any) {
      console.error("[WAYL_CHECKOUT_ERROR]", err);
      const message = err.message || "Failed to initiate checkout. Please try again.";
      setNotification({ type: 'error', message });
    } finally {
      setLoadingTier(null);
    }
  };

  return (
    <div className="flex flex-col items-center min-h-[calc(100vh-4rem)] p-6 bg-ink-900/10">
      <div className="max-w-6xl w-full space-y-8 mb-12 flex flex-col">
        
        {/* Header */}
        <div className="text-center mt-8 mb-4">
          <motion.h1 
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-4xl md:text-5xl font-extrabold text-white tracking-tight"
          >
            Simple, Transparent <span className="text-transparent bg-clip-text bg-gradient-to-r from-brand-400 to-accent-500">Pricing</span>
          </motion.h1>
          <motion.p 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="text-lg text-ink-300 max-w-2xl mx-auto text-center mt-4"
          >
            Pay securely with ZainCash, FIB, or Crypto via Wayl. No hidden fees. Get access to premium AI dubbing minutes instantly.
          </motion.p>
        </div>

        {/* User Notification Toast / Banner */}
        <AnimatePresence>
          {notification && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={`w-full max-w-2xl mx-auto p-4 rounded-xl border backdrop-blur-md flex items-center justify-between gap-4 shadow-lg ${
                notification.type === 'success'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  : 'border-rose-500/30 bg-rose-500/10 text-rose-300'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full ${notification.type === 'success' ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
                <span className="text-sm font-medium">{notification.message}</span>
              </div>
              <button 
                onClick={() => setNotification(null)}
                className="text-xs opacity-60 hover:opacity-100 uppercase tracking-wider font-semibold"
              >
                Dismiss
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Current Subscription Active Banner */}
        {userData && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full max-w-2xl mx-auto p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 backdrop-blur-md flex flex-col sm:flex-row items-center justify-between gap-4 text-center sm:text-left shadow-lg"
          >
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse shrink-0" />
              <div>
                <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Active Subscription</div>
                <div className="text-lg font-bold text-white">
                  You are currently on the <span className="text-emerald-400">{userData.plan || "Free"}</span> Plan
                </div>
              </div>
            </div>
            <div className="bg-ink-900/50 px-4 py-2 rounded-lg border border-white/5">
              <span className="text-xs text-ink-300 block">Minutes Balance</span>
              <span className="text-base font-extrabold text-white">{userData.remaining_minutes ?? 0} Min</span>
            </div>
          </motion.div>
        )}

        {/* Production Test Package (500 IQD) */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-2xl mx-auto p-4 rounded-xl border border-amber-500/40 bg-amber-500/10 backdrop-blur-md flex flex-col sm:flex-row items-center justify-between gap-4 shadow-lg text-center sm:text-left"
        >
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-amber-400 animate-ping shrink-0" />
            <div>
              <div className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Production Test Package</div>
              <div className="text-base font-bold text-white">
                Test Live Wayl Checkout — <span className="text-amber-300">500 IQD</span> (1 Min)
              </div>
            </div>
          </div>
          <button
            onClick={() => handleCheckout("test_500iqd")}
            disabled={loadingTier === "test_500iqd"}
            className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-ink-950 font-bold text-sm transition-all shadow-md hover:scale-105 disabled:opacity-50 shrink-0"
          >
            {loadingTier === "test_500iqd" ? "Redirecting..." : "Test Pay 1,000 IQD"}
          </button>
        </motion.div>


        {/* Pricing Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 w-full mt-8">
          <PricingCard
            id="starter"
            title="Starter"
            price="$10"
            minutes="5 Minutes"
            perMinute="$2.00 / min"
            description="Perfect for short clips and testing the platform."
            features={["HD Audio Exports", "Standard Voices", "Email Support"]}
            onCheckout={() => handleCheckout("starter")}
            isLoading={loadingTier === "starter"}
            delay={0.1}
            isCurrentPlan={currentPlan === "starter"}
          />
          
          <PricingCard
            id="pro"
            title="Pro"
            price="$20"
            minutes="15 Minutes"
            perMinute="$1.33 / min"
            description="The sweet spot for regular content creators."
            features={["Everything in Starter", "Premium Voices", "Priority Queue", "Commercial Rights"]}
            isPopular={true}
            onCheckout={() => handleCheckout("pro")}
            isLoading={loadingTier === "pro"}
            delay={0.2}
            isCurrentPlan={currentPlan === "pro"}
          />
          
          <PricingCard
            id="creator"
            title="Creator"
            price="$99"
            minutes="120 Minutes"
            perMinute="$0.82 / min"
            description="Massive value for high-volume video production."
            features={["Everything in Pro", "4K Video Exports", "API Access", "Dedicated 24/7 Support"]}
            onCheckout={() => handleCheckout("creator")}
            isLoading={loadingTier === "creator"}
            delay={0.3}
            isCurrentPlan={currentPlan === "creator"}
          />
        </div>
        
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="mt-16 flex items-center justify-center gap-2 text-ink-400 text-sm"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5 text-emerald-400">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Payments secured by <strong className="text-white">Wayl Gateway</strong>
        </motion.div>
      </div>
    </div>
  );
}
