import { Routes, Route } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import TopNav from "@/components/TopNav";
import GlobalPlayer from "@/components/GlobalPlayer";
import TextToSpeechPage from "@/pages/GeneratePage";
import VideoDubbingPage from "@/pages/VideoDubbingPage";
import VoiceLibraryPage from "@/pages/VoiceLibraryPage";
import HistoryPage from "@/pages/HistoryPage";
import PricingPage from "@/pages/PricingPage";
import BillingPage from "@/pages/BillingPage";
import SoraniqLandingPage from "@/pages/SoraniqLandingPage";
import CustomSignUpPage from "@/pages/CustomSignUpPage";
import AuthLayout from "@/components/AuthLayout";

import PrivacyPolicyPage from "@/pages/PrivacyPolicyPage";
import TermsOfServicePage from "@/pages/TermsOfServicePage";
import RefundPolicyPage from "@/pages/RefundPolicyPage";
import SettingsPage from "@/pages/SettingsPage";
import { ClerkProvider, SignedIn, SignedOut, SignIn, useAuth } from "@clerk/clerk-react";
import { ConvexProviderWithClerk } from "convex/react-clerk";
import { ConvexReactClient } from "convex/react";

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || "pk_test_ZGVjaWRpbmctcXVhZ2dhLTcwLmNsZXJrLmFjY291bnRzLmRldiQ";
const convex = new ConvexReactClient(import.meta.env.VITE_CONVEX_URL as string);

const clerkAppearance = {
  elements: {
    card: 'bg-transparent shadow-none px-0 w-full max-w-none',
    headerTitle: 'hidden',
    headerSubtitle: 'hidden',
    socialButtonsBlockButton: 'w-12 h-12 flex items-center justify-center rounded-full border border-brand-border hover:bg-brand-surface-bright transition-colors',
    formButtonPrimary: 'w-full bg-brand-sky hover:bg-opacity-90 text-brand-surface font-bold py-4 rounded-lg transition-all transform active:scale-[0.98]',
    formFieldInput: 'input-field w-full px-4 py-3 rounded-lg text-brand-text',
    formFieldLabel: 'block text-sm font-medium text-brand-text-muted mb-2',
    footerActionLink: 'text-brand-sky hover:underline font-medium',
    dividerLine: 'bg-brand-border',
    dividerText: 'text-brand-text-muted bg-transparent uppercase tracking-widest text-xs',
    identityPreviewText: 'text-brand-text',
    identityPreviewEditButton: 'text-brand-sky hover:text-opacity-80',
    formFieldInputShowPasswordButton: 'text-brand-text-muted hover:text-brand-text',
  },
  layout: {
    socialButtonsPlacement: 'bottom' as const,
    socialButtonsVariant: 'iconButton' as const,
  }
};

const SignInWithRedirect = () => {
  const params = new URLSearchParams(window.location.search);
  const redirectUrl = params.get('redirect_url') || '/tts';
  return (
    <AuthLayout title="Welcome back" subtitle="Please enter your account details to continue.">
      <SignIn appearance={clerkAppearance} routing="hash" signUpUrl={`/sign-up?redirect_url=${encodeURIComponent(redirectUrl)}`} fallbackRedirectUrl={redirectUrl} forceRedirectUrl={redirectUrl} />
    </AuthLayout>
  );
};

export default function App() {
  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <ConvexProviderWithClerk client={convex} useAuth={useAuth}>
        <Routes>
          {/* Public routes available to everyone */}
          <Route path="/" element={<SoraniqLandingPage />} />
          <Route path="/soraniq" element={<SoraniqLandingPage />} />
          <Route path="/:countryCode/soraniq" element={<SoraniqLandingPage />} />
          <Route path="/privacy-policy" element={<PrivacyPolicyPage />} />
          <Route path="/privacy" element={<PrivacyPolicyPage />} />
          <Route path="/terms-of-service" element={<TermsOfServicePage />} />
          <Route path="/terms" element={<TermsOfServicePage />} />
          <Route path="/refund-policy" element={<RefundPolicyPage />} />

          <Route
            path="*"
            element={
              <>
                <SignedOut>
                  <Routes>
                    <Route 
                      path="/sign-in/*" 
                      element={
                        <SignInWithRedirect />
                      } 
                    />
                    <Route path="/sign-up/*" element={<CustomSignUpPage />} />
                    <Route
                      path="*"
                      element={
                        <AuthLayout title="Welcome back" subtitle="Please enter your account details to continue.">
                          <SignIn 
                            appearance={clerkAppearance}
                            routing="hash" 
                            signUpUrl={`/sign-up?redirect_url=${encodeURIComponent(window.location.pathname + window.location.search)}`} 
                            fallbackRedirectUrl={window.location.pathname + window.location.search} 
                          />
                        </AuthLayout>
                      }
                    />
                  </Routes>
                </SignedOut>
                <SignedIn>
                  <div className="flex h-screen overflow-hidden">
                    <Sidebar />
                    <div className="flex-1 flex flex-col min-w-0 h-screen overflow-y-auto">
                      <TopNav />
                      <main className="flex-1">
                        <Routes>
                          <Route path="/tts" element={<TextToSpeechPage />} />
                          <Route path="/dubbing" element={<VideoDubbingPage />} />
                          <Route path="/voices" element={<VoiceLibraryPage />} />
                          <Route path="/history" element={<HistoryPage />} />
                          <Route path="/pricing" element={<PricingPage />} />
                          <Route path="/billing" element={<BillingPage />} />
                          <Route path="/settings" element={<SettingsPage />} />
                          <Route path="*" element={<TextToSpeechPage />} />
                        </Routes>
                      </main>
                    </div>
                    <GlobalPlayer />
                  </div>
                </SignedIn>
              </>
            }
          />
        </Routes>
      </ConvexProviderWithClerk>
    </ClerkProvider>
  );
}