import { useState, useEffect, useCallback, useRef } from "react";
import { useUser, useClerk, useAuth } from "@clerk/clerk-react";
import { getShieldStatus, setupShieldPin, verifyShieldPin } from "../api/adminApi";

const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes

export function useInactivityShield() {
  const { user } = useUser();
  const { signOut } = useClerk();
  const { getToken } = useAuth();
  const userId = user?.id || "";

  const [isLocked, setIsLocked] = useState<boolean>(true);
  const [hasConfiguredPin, setHasConfiguredPin] = useState<boolean>(true);
  const [isPermanentlyLocked, setIsPermanentlyLocked] = useState<boolean>(false);
  const [attemptsRemaining, setAttemptsRemaining] = useState<number>(5);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchShieldStatus = useCallback(async () => {
    if (!userId) return;
    try {
      const data = await getShieldStatus(getToken);
      setHasConfiguredPin(Boolean(data.hasPin));
      setIsPermanentlyLocked(Boolean(data.isPermanentlyLocked));
      setAttemptsRemaining(data.attemptsRemaining ?? 5);
      if (!data.hasPin) {
        setIsLocked(true);
      }
    } catch (e) {
      console.error("Shield status check failed", e);
    }
  }, [userId, getToken]);

  useEffect(() => {
    fetchShieldStatus();
  }, [fetchShieldStatus]);

  const resetTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setIsLocked(true);
    }, IDLE_TIMEOUT_MS);
  }, []);

  const unlockWithPin = useCallback(
    async (pin: string): Promise<{ success: boolean; error?: string }> => {
      try {
        await verifyShieldPin(getToken, pin);
        setIsLocked(false);
        setAttemptsRemaining(5);
        resetTimer();
        return { success: true };
      } catch (e: any) {
        if (e.status === 423) {
          setIsPermanentlyLocked(true);
          setTimeout(async () => {
            await signOut();
            window.location.href = "/sign-in";
          }, 1500);
          return {
            success: false,
            error: e.detail || "Account permanently locked. Terminating session...",
          };
        }
        return {
          success: false,
          error: e.detail || e.message || "Invalid PIN.",
        };
      }
    },
    [getToken, resetTimer, signOut]
  );

  const setupAndUnlock = useCallback(
    async (pin: string, confirmPin: string): Promise<{ success: boolean; error?: string }> => {
      try {
        await setupShieldPin(getToken, pin, confirmPin);
        setHasConfiguredPin(true);
        setIsLocked(false);
        resetTimer();
        return { success: true };
      } catch (e: any) {
        return {
          success: false,
          error: e.detail || e.message || "Setup failed.",
        };
      }
    },
    [getToken, resetTimer]
  );

  useEffect(() => {
    const events = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    const handleActivity = () => {
      if (!isLocked) {
        resetTimer();
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        setIsLocked(true);
      }
    };

    events.forEach((evt) => window.addEventListener(evt, handleActivity, { passive: true }));
    document.addEventListener("visibilitychange", handleVisibilityChange);

    resetTimer();

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      events.forEach((evt) => window.removeEventListener(evt, handleActivity));
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [isLocked, resetTimer]);

  return {
    isLocked,
    hasConfiguredPin,
    isPermanentlyLocked,
    attemptsRemaining,
    unlockWithPin,
    setupAndUnlock,
    lockNow: () => setIsLocked(true),
  };
}
