import React, { useState } from "react";
import { SignUp } from "@clerk/clerk-react";
import { Link } from "react-router-dom";

export default function CustomSignUpPage() {
  const [agreed, setAgreed] = useState(false);
  const [showSignUp, setShowSignUp] = useState(false);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#0b1220] py-12 px-4 sm:px-6 lg:px-8">
      {!showSignUp ? (
        <div className="max-w-md w-full space-y-8 bg-[#111114] p-8 rounded-2xl border border-[rgba(255,255,255,0.08)] shadow-2xl">
          <div className="text-center">
            <div className="mx-auto w-12 h-12 rounded-xl bg-gradient-to-br from-[#38bdf8] to-[#1a237e] p-0.5 flex items-center justify-center shadow-lg mb-4">
              <div className="w-full h-full bg-[#0a0a0b] rounded-[10px] flex items-center justify-center">
                <span className="text-[#38bdf8] font-bold text-xl tracking-tighter">SQ</span>
              </div>
            </div>
            <h2 className="mt-2 text-3xl font-extrabold text-[#fafafa]">
              Create your account
            </h2>
            <p className="mt-2 text-sm text-[#cfcfd3]">
              Start dubbing your videos today
            </p>
          </div>

          <div className="mt-8 space-y-6">
            <div className="bg-[#0a0a0b] border border-[rgba(255,255,255,0.06)] rounded-xl p-6">
              <h3 className="text-lg font-medium text-[#fafafa] mb-4">Terms of Service & Privacy</h3>
              <p className="text-sm text-[#cfcfd3] mb-6">
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
                    className="w-5 h-5 bg-[#111114] border border-[rgba(255,255,255,0.2)] rounded cursor-pointer accent-[#38bdf8]"
                  />
                </div>
                <div className="ml-3 text-sm">
                  <label htmlFor="terms" className="font-medium text-[#cfcfd3] cursor-pointer">
                    I agree to the{" "}
                    <Link to="/terms" className="text-[#38bdf8] hover:underline" target="_blank">
                      Terms of Service
                    </Link>{" "}
                    and{" "}
                    <Link to="/privacy" className="text-[#38bdf8] hover:underline" target="_blank">
                      Privacy Policy
                    </Link>.
                  </label>
                </div>
              </div>

              <button
                disabled={!agreed}
                onClick={() => setShowSignUp(true)}
                className={`w-full flex justify-center py-3 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-[#0a0a0b] ${
                  agreed 
                    ? "bg-[#38bdf8] hover:bg-[#38bdf8]/90 cursor-pointer" 
                    : "bg-[#38bdf8]/50 cursor-not-allowed"
                } transition-colors`}
              >
                Continue to Sign Up
              </button>
            </div>
            
            <div className="text-center">
              <p className="text-sm text-[#cfcfd3]">
                Already have an account?{" "}
                <Link to="/sign-in" className="font-medium text-[#38bdf8] hover:underline">
                  Sign in
                </Link>
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="w-full max-w-md flex justify-center animate-in fade-in zoom-in duration-300">
          <SignUp routing="hash" signInUrl="/sign-in" fallbackRedirectUrl="/tts" />
        </div>
      )}
    </div>
  );
}
