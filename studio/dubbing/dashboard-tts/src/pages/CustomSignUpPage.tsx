import React, { useState } from "react";
import { SignUp } from "@clerk/clerk-react";
import { Link, useSearchParams } from "react-router-dom";
import AuthLayout from "@/components/AuthLayout";

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

export default function CustomSignUpPage() {
  const [searchParams] = useSearchParams();
  const redirectUrl = searchParams.get("redirect_url") || "/tts";

  return (
    <AuthLayout 
      title="Create your account" 
      subtitle="Start dubbing your videos today"
    >
      <div className="w-full animate-in fade-in zoom-in duration-300">
        <SignUp 
          appearance={clerkAppearance} 
          routing="hash" 
          signInUrl={`/sign-in?redirect_url=${encodeURIComponent(redirectUrl)}`} 
          fallbackRedirectUrl={redirectUrl} 
          forceRedirectUrl={redirectUrl} 
        />
      </div>
    </AuthLayout>
  );
}
