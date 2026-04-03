import { createBrowserRouter } from "react-router";
import { RootLayout } from "./components/root-layout";
import { CaseList } from "./components/case-list";
import { CaseDetail } from "./components/case-detail";
import { Login } from "./components/login";
import { Signup } from "./components/signup";
import { ForgotPassword } from "./components/forgot-password";
import { ProtectedRoute } from "./components/protected-route";
import { DesignSystemShowcase } from "./components/design-system-showcase";
import { LeadList } from "./components/leads/lead-list";
import { LeadDetail } from "./components/leads/lead-detail";
import { AttorneyReviewQueue } from "./components/attorney/review-queue";
import { AttorneyCaseReviewDetail } from "./components/attorney/case-review-detail";
import { SettlementCalculator } from "./components/settlement/settlement-calculator";
import { AdminLayout } from "./components/admin/admin-layout";
import { AdminHome } from "./components/admin/admin-home";
import { UserList } from "./components/admin/user-list";
import { UserForm } from "./components/admin/user-form";
import { SystemSettings } from "./components/admin/system-settings";
import { IntegrationDashboard } from "./components/admin/integration-dashboard";
import { AuditLog } from "./components/admin/audit-log";

export const router = createBrowserRouter([
  {
    path: "/login",
    Component: Login,
  },
  {
    path: "/signup",
    Component: Signup,
  },
  {
    path: "/forgot-password",
    Component: ForgotPassword,
  },
  {
    path: "/design-system",
    Component: DesignSystemShowcase,
  },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <RootLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        index: true,
        Component: CaseList,
      },
      {
        path: "case/:caseId",
        Component: CaseDetail,
      },
      {
        path: "leads",
        Component: LeadList,
      },
      {
        path: "leads/:leadId",
        Component: LeadDetail,
      },
      // Attorney Review Routes
      {
        path: "attorney/review",
        Component: AttorneyReviewQueue,
      },
      {
        path: "attorney/review/:caseId",
        Component: AttorneyCaseReviewDetail,
      },
      // Settlement Calculator Route
      {
        path: "settlement-calculator",
        Component: SettlementCalculator,
      },
      {
        path: "settlement-calculator/:caseId",
        Component: SettlementCalculator,
      },
    ],
  },
  {
    path: "/admin",
    element: (
      <ProtectedRoute>
        <AdminLayout />
      </ProtectedRoute>
    ),
    children: [
      {
        index: true,
        Component: AdminHome,
      },
      {
        path: "home",
        Component: AdminHome,
      },
      {
        path: "users",
        Component: UserList,
      },
      {
        path: "users/new",
        Component: UserForm,
      },
      {
        path: "users/:userId/edit",
        Component: UserForm,
      },
      {
        path: "settings",
        Component: SystemSettings,
      },
      {
        path: "integrations",
        Component: IntegrationDashboard,
      },
      {
        path: "audit-log",
        Component: AuditLog,
      },
    ],
  },
]);