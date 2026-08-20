import React from "react";
import { useUser } from "@clerk/clerk-react";
import { Navigate } from "react-router-dom";

export const AdminRoute = ({ children }: { children: React.ReactNode }) => {
  const { isLoaded, isSignedIn, user } = useUser();

  if (!isLoaded) {
    return (
      <div className="flex h-screen items-center justify-center bg-ink-950 text-white font-mono text-sm">
        <div className="flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-brand-400 border-t-transparent rounded-full animate-spin" />
          <span>Verifying zero-trust admin credentials...</span>
        </div>
      </div>
    );
  }

  if (!isSignedIn) {
    return <Navigate to={`/sign-in?redirect_url=${encodeURIComponent("/admin")}`} replace />;
  }

  const role = (user?.publicMetadata?.role as string) || (user?.organizationMemberships?.[0]?.role as string) || "";
  const isAdmin = role === "admin" || role === "org:admin" || role === "super_admin";

  if (!isAdmin) {
    return (
      <div className="flex h-screen items-center justify-center bg-ink-950 p-6">
        <div className="max-w-md w-full rounded-2xl border border-red-500/20 bg-ink-900/90 p-8 text-center backdrop-blur-xl shadow-2xl">
          <div className="w-12 h-12 rounded-xl bg-red-500/10 text-red-400 mx-auto flex items-center justify-center mb-4 text-2xl font-bold">
            🛡️
          </div>
          <h1 className="text-xl font-bold text-red-400 mb-2 font-mono">403 — Unauthorized</h1>
          <p className="text-sm text-ink-400 mb-6">
            Account <span className="text-ink-200 font-mono">{user?.primaryEmailAddress?.emailAddress}</span> does not possess administrative privileges.
          </p>
          <a
            href="/tts"
            className="inline-block px-5 py-2.5 rounded-lg bg-ink-800 hover:bg-ink-700 text-ink-200 text-xs font-semibold uppercase tracking-wider transition-colors"
          >
            Return to Dubbing Studio
          </a>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};

export default AdminRoute;
