import React from "react";
import { Routes, Route } from "react-router-dom";
import AdminLayout from "../../components/admin/AdminLayout";
import SystemDashboardView from "./SystemDashboardView";
import JobOperationsView from "./JobOperationsView";
import UserIntelligenceView from "./UserIntelligenceView";
import FinancialLedgerView from "./FinancialLedgerView";
import SecurityAccessView from "./SecurityAccessView";
import PendingApprovalsView from "./PendingApprovalsView";
import AuditLogsView from "./AuditLogsView";
import TelegramCommandView from "./TelegramCommandView";
import SystemConfigsView from "./SystemConfigsView";
import AdminLogoutView from "./AdminLogoutView";

export const AdminPage: React.FC = () => {
  return (
    <AdminLayout>
      <Routes>
        <Route path="/" element={<SystemDashboardView />} />
        <Route path="/jobs" element={<JobOperationsView />} />
        <Route path="/users" element={<UserIntelligenceView />} />
        <Route path="/ledger" element={<FinancialLedgerView />} />
        <Route path="/security" element={<SecurityAccessView />} />
        <Route path="/approvals" element={<PendingApprovalsView />} />
        <Route path="/audit" element={<AuditLogsView />} />
        <Route path="/telegram" element={<TelegramCommandView />} />
        <Route path="/configs" element={<SystemConfigsView />} />
        <Route path="/logout" element={<AdminLogoutView />} />
      </Routes>
    </AdminLayout>
  );
};

export default AdminPage;
