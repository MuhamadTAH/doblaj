import React, { useEffect } from "react";
import { useClerk } from "@clerk/clerk-react";
import { useNavigate } from "react-router-dom";

export const AdminLogoutView: React.FC = () => {
  const { signOut } = useClerk();
  const navigate = useNavigate();

  useEffect(() => {
    const performLogout = async () => {
      try {
        localStorage.removeItem("clerk-db-jwt");
        localStorage.removeItem("is_impersonating");
        localStorage.removeItem("impersonated_email");
        localStorage.removeItem("admin_shield_pin");
        await signOut();
      } catch (e) {
        console.error("Logout error", e);
      } finally {
        navigate("/sign-in?redirect_url=/admin");
      }
    };
    performLogout();
  }, [signOut, navigate]);

  return (
    <div className="flex h-screen items-center justify-center bg-ink-950 text-white font-mono text-xs">
      <div className="flex items-center gap-3">
        <div className="w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full animate-spin" />
        <span>Terminating admin session and clearing credentials...</span>
      </div>
    </div>
  );
};

export default AdminLogoutView;
