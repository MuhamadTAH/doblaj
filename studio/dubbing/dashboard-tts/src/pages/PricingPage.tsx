import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import PricingCard from "@/components/PricingCard";
import { useAuth } from "@clerk/clerk-react";
import { useSearchParams, useNavigate } from "react-router-dom";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");


export default function PricingPage() {
  const [loadingTier, setLoadingTier] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [userData, setUserData] = useState<any>(null);
  const { getToken } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const hasTriggeredCheckout = useRef(false);
  const navigate = useNavigate();

  useEffect(() => {
    async function fetchUserPlan() {
      try {
        const token = await getToken({ template: 'convex' });
        if (!token) return;
        const res = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` }
        });
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

  const handleCheckout = async (tierId: string) => {
    setLoadingTier(tierId);
    try {
      const token = await getToken({ template: 'convex' });
      const res = await fetch(`${API_BASE}/api/payments/checkout`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ tier: tierId })
      });

      if (!res.ok) {
        let errorMsg = "Failed to create checkout session";
        try {
          const errorData = await res.json();
          errorMsg = errorData.detail || errorMsg;
        } catch {
          errorMsg = `Server error (${res.status}). Please check backend logs and environment variables.`;
        }
        throw new Error(errorMsg);
      }

      const data = await res.json().catch(() => {
        throw new Error("Invalid response format from server");
      });
      if (data.checkoutUrl) {
        window.location.href = data.checkoutUrl;
      } else {
        throw new Error("Invalid response from server");
      }
    } catch (err: any) {
      console.error(err);
      alert(err.message || "Failed to initiate checkout. Please try again.");
    } finally {
      setLoadingTier(null);
    }
  };

  useEffect(() => {
    const plan = searchParams.get("plan");
    if (plan && !hasTriggeredCheckout.current) {
      hasTriggeredCheckout.current = true;
      // Remove the search param so it doesn't re-trigger if they go back
      setSearchParams({});
      handleCheckout(plan);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, setSearchParams]);

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
            Pay securely with credit card. No hidden fees. Get access to premium AI dubbing minutes instantly.
          </motion.p>
        </div>

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
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5 text-green-400">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
          Payments secured by <strong className="text-white">Suby Checkout</strong>
        </motion.div>
      </div>
    </div>
  );
}
