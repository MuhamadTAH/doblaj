import { useState, useEffect, useCallback, useRef } from "react";
import { useUser, useClerk } from "@clerk/clerk-react";

const IDLE_TIMEOUT_MS = 60 * 1000; // 60 seconds

export function useInactivityShield() {
  const { user } = useUser();
  const { signOut } = useClerk();
  const userId = user?.id || "";

  const [isLocked, setIsLocked] = useState<boolean>(true);
  const [hasConfiguredPin, setHasConfiguredPin] = useState<boolean>(true);
  const [isPermanentlyLocked, setIsPermanentlyLocked] = useState<boolean>(false);
  const [attemptsRemaining, setAttemptsRemaining] = useState<number>(5);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchShieldStatus = useCallback(async () => {
    if (!userId) return;
    try {
      const token = localStorage.getItem("clerk-db-jwt") || "";
      const res = await fetch("/api/admin/shield/status", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setHasConfiguredPin(Boolean(data.hasPin));
        setIsPermanentlyLocked(Boolean(data.isPermanentlyLocked));
        setAttemptsRemaining(data.attemptsRemaining ?? 5);
        if (!data.hasPin) {
          setIsLocked(true);
        }
      }
    } catch (e) {
      console.error("Shield status check failed", e);
    }
  }, [userId]);

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
        const token = localStorage.getItem("clerk-db-jwt") || "";
        const res = await fetch("/api/admin/shield/verify-pin", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ pin }),
        });

        if (res.ok) {
          setIsLocked(false);
          setAttemptsRemaining(5);
          resetTimer();
          return { success: true };
        }

        const data = await res.json();
        if (res.status === 423) {
          setIsPermanentlyLocked(true);
          setTimeout(async () => {
            await signOut();
            window.location.href = "/sign-in";
          }, 1500);
          return {
            success: false,
            error: data.detail || "Account permanently locked. Session terminating...",
          };
        }

        return {
          success: false,
          error: data.detail || "Invalid PIN.",
        };
      } catch (e: any) {
        return {
          success: false,
          error: `Network error: ${e.message}. Screen remains locked.`,
        };
      }
    },
    [resetTimer, signOut]
  );

  const setupAndUnlock = useCallback(
    async (pin: string, confirmPin: string): Promise<{ success: boolean; error?: string }> => {
      try {
        const token = localStorage.getItem("clerk-db-jwt") || "";
        const res = await fetch("/api/admin/shield/setup-pin", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ pin, confirm_pin: confirmPin }),
        });

        if (res.ok) {
          setHasConfiguredPin(true);
          setIsLocked(false);
          resetTimer();
          return { success: true };
        }

        const data = await res.json();
        return { success: false, error: data.detail || "Setup failed" };
      } catch (e: any) {
        return { success: false, error: `Network error: ${e.message}` };
      }
    },
    [resetTimer]
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
