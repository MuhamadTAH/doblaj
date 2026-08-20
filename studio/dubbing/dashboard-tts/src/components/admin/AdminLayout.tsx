import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useUser, useClerk } from "@clerk/clerk-react";
import { useInactivityShield } from "../../hooks/useInactivityShield";
import PinLockView from "./PinLockView";

interface AdminLayoutProps {
  children: React.ReactNode;
}

const navItems = [
  { to: "/admin", label: "Command Center", icon: "📊", exact: true },
  { to: "/admin/jobs", label: "Job Operations & DLQ", icon: "🏭" },
  { to: "/admin/users", label: "User Intelligence (CRM)", icon: "👥" },
  { to: "/admin/ledger", label: "Financial Ledger", icon: "💳" },
  { to: "/admin/security", label: "Security & RBAC", icon: "🛡️" },
  { to: "/admin/approvals", label: "Pending Approvals", icon: "⏳" },
  { to: "/admin/audit", label: "Audit Logs", icon: "📜" },
  { to: "/admin/telegram", label: "Telegram Live", icon: "💬" },
  { to: "/admin/configs", label: "System Configs", icon: "⚙️" },
];

export const AdminLayout: React.FC<AdminLayoutProps> = ({ children }) => {
  const { user } = useUser();
  const { signOut } = useClerk();
  const navigate = useNavigate();
  const { isLocked, hasConfiguredPin, isPermanentlyLocked, unlockWithPin, setupAndUnlock, lockNow } = useInactivityShield();

  // True unmount defense: If locked, children are completely UNMOUNTED from the virtual DOM
  if (isLocked) {
    return (
      <PinLockView
        hasConfiguredPin={hasConfiguredPin}
        isPermanentlyLocked={isPermanentlyLocked}
        onUnlock={unlockWithPin}
        onSetupPin={setupAndUnlock}
      />
    );
  }

  const handleLogout = async () => {
    await signOut();
    navigate("/sign-in");
  };

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100 flex flex-col font-sans selection:bg-brand-500/30">
      {/* Top Header */}
      <header className="sticky top-0 z-40 border-b border-white/[0.08] bg-ink-950/80 backdrop-blur-xl px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-accent-500 flex items-center justify-center text-white font-bold text-sm shadow-glow">
              🛡️
            </div>
            <div>
              <span className="font-bold text-white tracking-tight text-sm flex items-center gap-2">
                PIRD ADMIN COMMAND
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  PRODUCTION
                </span>
              </span>
              <p className="text-[11px] text-ink-400 font-mono">Zero-Trust Operational Architecture</p>
            </div>
          </div>
        </div>

        {/* User / Actions */}
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-xs font-mono text-ink-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>{user?.primaryEmailAddress?.emailAddress}</span>
            <span className="text-ink-500">|</span>
            <span className="text-brand-400 uppercase font-semibold">
              {(user?.publicMetadata?.role as string) || "ADMIN"}
            </span>
          </div>

          <button
            onClick={lockNow}
            title="Lock screen now (Shield DOM)"
            className="p-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-ink-300 hover:text-white border border-white/[0.06] transition-colors text-xs flex items-center gap-1.5"
          >
            🔒 <span className="hidden md:inline font-mono">Lock Shield</span>
          </button>

          <button
            onClick={handleLogout}
            className="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 text-xs font-semibold tracking-wider transition-colors flex items-center gap-1.5"
          >
            🚪 <span>Logout</span>
          </button>
        </div>
      </header>

      {/* Sub Navigation Bar */}
      <nav className="border-b border-white/[0.06] bg-ink-900/40 px-6 overflow-x-auto flex gap-1 py-1.5 scrollbar-none">
        {navItems.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.exact}
            className={({ isActive }) =>
              `px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap flex items-center gap-2 transition-all ${
                isActive
                  ? "bg-brand-500/15 text-brand-300 border border-brand-500/30 shadow-sm"
                  : "text-ink-400 hover:text-ink-200 hover:bg-white/[0.03]"
              }`
            }
          >
            <span>{it.icon}</span>
            <span>{it.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Main Content Area */}
      <main className="flex-1 p-6 max-w-7xl w-full mx-auto">{children}</main>
    </div>
  );
};

export default AdminLayout;
