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
    card: 'bg-transparent shadow-none px-0',
    headerTitle: 'hidden',
    headerSubtitle: 'hidden',
    socialButtonsBlockButton: 'border border-white/[0.08] hover:bg-white/[0.04] text-white',
    formButtonPrimary: 'bg-brand-400 hover:bg-brand-500 text-ink-950 font-bold',
    formFieldInput: 'bg-ink-900 border-white/[0.1] text-white focus:border-brand-400 focus:ring-brand-400',
    formFieldLabel: 'text-ink-200',
    footerActionLink: 'text-brand-400 hover:text-brand-300',
    dividerLine: 'bg-white/[0.08]',
    dividerText: 'text-ink-400 bg-transparent',
    identityPreviewText: 'text-white',
    identityPreviewEditButton: 'text-brand-400 hover:text-brand-300',
    formFieldInputShowPasswordButton: 'text-ink-400 hover:text-white',
  },
  layout: {
    socialButtonsPlacement: 'bottom' as const,
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