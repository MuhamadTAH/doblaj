import React, { useState } from "react";
import { motion } from "framer-motion";

interface PinLockViewProps {
  hasConfiguredPin: boolean;
  isPermanentlyLocked?: boolean;
  onUnlock: (pin: string) => Promise<{ success: boolean; error?: string }>;
  onSetupPin: (pin: string, confirmPin: string) => Promise<{ success: boolean; error?: string }>;
}

export const PinLockView: React.FC<PinLockViewProps> = ({
  hasConfiguredPin,
  isPermanentlyLocked,
  onUnlock,
  onSetupPin,
}) => {
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isSetupMode = !hasConfiguredPin;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setIsSubmitting(true);

    try {
      if (isSetupMode) {
        if (pin.length !== 6 || !/^\d+$/.test(pin)) {
          setErrorMsg("PIN must be exactly 6 numeric digits.");
          setIsSubmitting(false);
          return;
        }
        if (pin !== confirmPin) {
          setErrorMsg("PINs do not match. Please re-enter.");
          setIsSubmitting(false);
          return;
        }
        const res = await onSetupPin(pin, confirmPin);
        if (!res.success) {
          setErrorMsg(res.error || "Failed to initialize PIN on server.");
        }
      } else {
        const res = await onUnlock(pin);
        if (res.success) {
          setPin("");
        } else {
          setPin("");
          setErrorMsg(res.error || "Invalid PIN.");
        }
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950 p-4 select-none">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-sm rounded-3xl border border-white/10 bg-ink-900/95 p-8 text-center shadow-2xl backdrop-blur-2xl"
      >
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-tr from-brand-500/20 to-accent-500/20 text-brand-400 border border-brand-500/30">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
            />
          </svg>
        </div>

        <h2 className="text-lg font-bold text-white tracking-tight">
          {isPermanentlyLocked
            ? "Account Permanently Locked"
            : isSetupMode
            ? "Configure Admin Shield PIN"
            : "Admin Session Shield"}
        </h2>
        <p className="mt-1 text-xs text-ink-400">
          {isPermanentlyLocked
            ? "5 strikes exceeded. Contact Super Admin."
            : isSetupMode
            ? "Initialize your 6-digit PIN securely hashed with server-side Argon2id."
            : "Dashboard unmounted due to inactivity. Enter PIN to decrypt virtual DOM."}
        </p>

        {!isPermanentlyLocked && (
          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <div className="space-y-3">
              <input
                type="password"
                inputMode="numeric"
                maxLength={6}
                autoFocus
                value={pin}
                onChange={(e) => {
                  setPin(e.target.value.replace(/\D/g, ""));
                  setErrorMsg(null);
                }}
                placeholder={isSetupMode ? "Create 6-Digit PIN" : "••••••"}
                className={`w-full text-center tracking-[0.6em] text-2xl font-mono py-3 px-4 rounded-xl border bg-ink-950 text-white placeholder:text-ink-600 focus:outline-none transition-all ${
                  errorMsg
                    ? "border-red-500/60 ring-2 ring-red-500/20"
                    : "border-white/10 focus:border-brand-400/60 focus:ring-2 focus:ring-brand-400/20"
                }`}
              />

              {isSetupMode && (
                <input
                  type="password"
                  inputMode="numeric"
                  maxLength={6}
                  value={confirmPin}
                  onChange={(e) => {
                    setConfirmPin(e.target.value.replace(/\D/g, ""));
                    setErrorMsg(null);
                  }}
                  placeholder="Confirm 6-Digit PIN"
                  className="w-full text-center tracking-[0.6em] text-2xl font-mono py-3 px-4 rounded-xl border border-white/10 bg-ink-950 text-white placeholder:text-ink-600 focus:outline-none focus:border-brand-400/60 focus:ring-2 focus:ring-brand-400/20 transition-all"
                />
              )}
            </div>

            {errorMsg && (
              <p className="text-xs text-red-400 font-mono animate-shake">
                {errorMsg}
              </p>
            )}

            <button
              type="submit"
              disabled={isSubmitting || pin.length !== 6 || (isSetupMode && confirmPin.length !== 6)}
              className="w-full rounded-xl bg-gradient-to-r from-brand-500 to-accent-500 py-3 text-xs font-bold uppercase tracking-wider text-white shadow-lg shadow-brand-500/20 hover:brightness-110 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {isSubmitting
                ? "Verifying Server..."
                : isSetupMode
                ? "Initialize on Server"
                : "Unlock Session"}
            </button>
          </form>
        )}

        <div className="mt-6 border-t border-white/5 pt-4 text-[10px] text-ink-500 font-mono">
          PIRD ZERO-TRUST PROTOCOL • SERVER-SIDE ARGON2ID & STRIKE GATED
        </div>
      </motion.div>
    </div>
  );
};

export default PinLockView;
