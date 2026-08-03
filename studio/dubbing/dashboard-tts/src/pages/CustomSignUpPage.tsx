import React, { useState } from "react";
import { SignUp } from "@clerk/clerk-react";
import { Link, useSearchParams } from "react-router-dom";
import AuthLayout from "@/components/AuthLayout";

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

export default function CustomSignUpPage() {
  const [agreed, setAgreed] = useState(false);
  const [showSignUp, setShowSignUp] = useState(false);
  const [searchParams] = useSearchParams();
  const redirectUrl = searchParams.get("redirect_url") || "/tts";

  return (
    <AuthLayout 
      title="Create your account" 
      subtitle="Start dubbing your videos today"
    >
      {!showSignUp ? (
        <div className="space-y-6">
          <div className="bg-ink-900/50 border border-white/[0.06] rounded-xl p-6">
            <h3 className="text-lg font-medium text-white mb-4">Terms of Service & Privacy</h3>
            <p className="text-sm text-ink-200 mb-6">
              Before creating an account, please review and accept our terms and privacy policy.
            </p>
            
            <div className="flex items-start mb-6">
              <div className="flex items-center h-5">
                <input
                  id="terms"
                  name="terms"
                  type="checkbox"
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                  className="w-5 h-5 bg-ink-900 border border-white/[0.2] rounded cursor-pointer text-brand-400 focus:ring-brand-400"
                />
              </div>
              <div className="ml-3 text-sm">
                <label htmlFor="terms" className="font-medium text-ink-200 cursor-pointer">
                  I agree to the{" "}
                  <Link to="/terms" className="text-brand-400 hover:underline" target="_blank">
                    Terms of Service
                  </Link>{" "}
                  and{" "}
                  <Link to="/privacy" className="text-brand-400 hover:underline" target="_blank">
                    Privacy Policy
                  </Link>.
                </label>
              </div>
            </div>

            <button
              disabled={!agreed}
              onClick={() => setShowSignUp(true)}
              className={`w-full flex justify-center py-4 px-4 border border-transparent rounded-lg shadow-sm text-sm font-bold text-ink-950 ${
                agreed 
                  ? "bg-brand-400 hover:bg-brand-500 cursor-pointer transform active:scale-[0.98]" 
                  : "bg-brand-400/50 cursor-not-allowed"
              } transition-all`}
            >
              Continue to Sign Up
            </button>
          </div>
          
          <div className="text-center">
            <p className="text-sm text-ink-200">
              Already have an account?{" "}
              <Link to={`/sign-in?redirect_url=${encodeURIComponent(redirectUrl)}`} className="font-medium text-brand-400 hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      ) : (
        <div className="w-full animate-in fade-in zoom-in duration-300">
          <SignUp 
            appearance={clerkAppearance} 
            routing="hash" 
            signInUrl={`/sign-in?redirect_url=${encodeURIComponent(redirectUrl)}`} 
            fallbackRedirectUrl={redirectUrl} 
            forceRedirectUrl={redirectUrl} 
          />
        </div>
      )}
    </AuthLayout>
  );
}
