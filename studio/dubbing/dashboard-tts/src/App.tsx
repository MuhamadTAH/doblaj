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

import PrivacyPolicyPage from "@/pages/PrivacyPolicyPage";
import TermsOfServicePage from "@/pages/TermsOfServicePage";
import RefundPolicyPage from "@/pages/RefundPolicyPage";
import SettingsPage from "@/pages/SettingsPage";
import { ClerkProvider, SignedIn, SignedOut, SignIn, useAuth } from "@clerk/clerk-react";
import { ConvexProviderWithClerk } from "convex/react-clerk";
import { ConvexReactClient } from "convex/react";

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || "pk_test_ZGVjaWRpbmctcXVhZ2dhLTcwLmNsZXJrLmFjY291bnRzLmRldiQ";
const convex = new ConvexReactClient(import.meta.env.VITE_CONVEX_URL as string);

const SignInWithRedirect = () => {
  const params = new URLSearchParams(window.location.search);
  const redirectUrl = params.get('redirect_url') || '/tts';
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-[#0b1220]">
      <SignIn routing="hash" signUpUrl={`/sign-up?redirect_url=${encodeURIComponent(redirectUrl)}`} fallbackRedirectUrl={redirectUrl} forceRedirectUrl={redirectUrl} />
    </div>
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
                        <div className="flex h-screen w-screen items-center justify-center bg-[#0b1220]">
                          <SignIn 
                            routing="hash" 
                            signUpUrl={`/sign-up?redirect_url=${encodeURIComponent(window.location.pathname + window.location.search)}`} 
                            fallbackRedirectUrl={window.location.pathname + window.location.search} 
                          />
                        </div>
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