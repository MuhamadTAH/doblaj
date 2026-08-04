import React from "react";
import { motion } from "framer-motion";

interface PricingCardProps {
  id: string;
  title: string;
  price: string;
  minutes: string;
  perMinute: string;
  description: string;
  features: string[];
  isPopular?: boolean;
  onCheckout: () => void;
  isLoading: boolean;
  delay: number;
  isCurrentPlan?: boolean;
}

export default function PricingCard({
  id,
  title,
  price,
  minutes,
  perMinute,
  description,
  features,
  isPopular,
  onCheckout,
  isLoading,
  delay,
  isCurrentPlan
}: PricingCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className={`relative flex flex-col p-6 sm:p-8 rounded-2xl border bg-ink-900/60 backdrop-blur-xl
        ${isCurrentPlan 
          ? "border-emerald-500 shadow-glow shadow-emerald-500/20 transform md:-translate-y-2" 
          : isPopular 
            ? "border-brand-500 shadow-glow shadow-brand-500/20 transform md:-translate-y-2" 
            : "border-white/[0.08]"
        }
      `}
    >
      {(isPopular || isCurrentPlan) && (
        <div className={`absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 px-3 py-1 text-white text-xs font-bold uppercase tracking-widest rounded-full shadow-lg ${isCurrentPlan ? 'bg-gradient-to-r from-emerald-500 to-emerald-400' : 'bg-gradient-to-r from-brand-400 to-accent-500'}`}>
          {isCurrentPlan ? "Current Plan" : "Most Popular"}
        </div>
      )}

      <div className="mb-6">
        <h3 className="text-xl font-semibold text-white mb-2">{title}</h3>
        <p className="text-ink-400 text-sm h-10">{description}</p>
      </div>

      <div className="mb-6 flex items-baseline gap-2">
        <span className="text-4xl font-extrabold text-white">{price}</span>
        <span className="text-ink-300 font-medium">for {minutes}</span>
      </div>
      
      <div className="mb-8">
        <div className="inline-block px-2 py-1 bg-white/[0.04] rounded text-xs text-ink-300 font-mono mb-4 border border-white/[0.04]">
          {perMinute}
        </div>
        <ul className="space-y-3">
          {features.map((feat, i) => (
            <li key={i} className="flex items-start gap-3 text-ink-200 text-sm">
              <svg className="w-5 h-5 shrink-0 text-brand-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span>{feat}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto pt-6 border-t border-white/[0.06]">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onCheckout}
          disabled={isLoading}
          className={`w-full py-3 px-4 rounded-xl font-bold transition-all flex items-center justify-center gap-2
            ${isCurrentPlan
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
              : isPopular
                ? "bg-gradient-to-r from-brand-500 to-accent-600 text-white shadow-lg hover:shadow-brand-500/25"
                : "bg-white/[0.08] text-white hover:bg-white/[0.12]"
            }
            ${isLoading ? "opacity-75 cursor-not-allowed" : ""}
          `}
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Processing...
            </span>
          ) : isCurrentPlan ? (
            `Current Plan (Buy More)`
          ) : (
            `Get ${minutes}`
          )}
        </motion.button>
      </div>
    </motion.div>
  );
}
