import React from "react";

export default function TermsOfServicePage() {
  return (
    <div className="p-8 max-w-4xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Terms of Service</h1>
      
      <div className="prose prose-invert max-w-none">
        <p className="mb-4">
          <strong>Effective Date:</strong> July 28, 2026
        </p>

        <p className="mb-4">
          These Terms of Service ("Terms") govern the services provided by FIXDAI LLC, doing business as Doblaj (operating the website doblaj.com) ("we," "us," or "our"). By accessing, subscribing to, or using the Doblaj B2B SaaS platform and services (collectively, the "Services"), you agree to be bound by these Terms.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">1. Subscription, Billing, and Renewal</h2>
        <p className="mb-4">
          <strong>Fulfillment & Service Delivery:</strong> Doblaj is a B2B Software-as-a-Service (SaaS) platform. SaaS access, credit allocations, and digital processing capabilities are delivered immediately upon successful payment confirmation.
        </p>
        <p className="mb-4">
          <strong>Negative Option / Auto-Renewal Billing:</strong> Subscriptions are billed on a recurring basis (monthly or annually) according to your selected plan. <em>Your subscription will automatically renew at the end of each billing cycle, and your payment method on file will be charged the then-current subscription fee unless you cancel your subscription prior to the renewal date.</em>
        </p>
        <p className="mb-4">
          <strong>Self-Serve Cancellation:</strong> You may cancel your subscription at any time via a self-serve method online by navigating to your Doblaj Account Settings (<code>/tts/settings</code>) or billing portal. Cancellation will take effect at the end of your current prepaid billing period. You will retain access to the Services through the remainder of the paid period, and no further recurring charges will be initiated.
        </p>

        <h3 className="text-xl font-semibold mt-6 mb-3">1.1 Refund Policy</h3>
        <p className="mb-4">
          <strong>Strict No-Refund Policy:</strong> Due to the immediate digital delivery of cloud compute resources, third-party AI model costs, and processing power, all subscription payments, credit purchases, and usage fees are strictly non-refundable. We do not provide refunds or credits for partial subscription cycles, unused credits, or unconsumed plan allocations.
        </p>
        <p className="mb-4">
          <strong>Statutory Rights & Exceptions:</strong> Nothing in this section limits any mandatory statutory rights available under applicable law where non-excludable consumer protections apply. Refund requests resulting from technical billing errors verified by FIXDAI LLC will be evaluated on a case-by-case basis at our sole discretion. Please review our full <a href="/refund-policy" className="text-brand-400 underline">Refund Policy</a> for further details.
        </p>

        <h3 className="text-xl font-semibold mt-6 mb-3">1.2 KYC, Limits & Anti-Fraud</h3>
        <p className="mb-4">
          <strong>Account Verification:</strong> To ensure platform security and comply with applicable anti-money laundering (AML) and "Know Your Customer" (KYC) requirements, we may enforce transaction limits or require identity verification (such as government-issued ID or business registration) for high-volume accounts or suspicious payment patterns. Failure to comply with KYC requests may result in account suspension without refund.
        </p>

        <h3 className="text-xl font-semibold mt-6 mb-3">1.3 Chargeback & Payment Disputes</h3>
        <p className="mb-4">
          <strong>Dispute Mechanisms:</strong> If you believe there is a billing error, you must contact our support team at <a href="mailto:billing@doblaj.com" className="text-brand-400 underline">billing@doblaj.com</a> within 30 days of the charge. We will investigate and resolve legitimate errors.
        </p>
        <p className="mb-4">
          <strong>Fraudulent Chargebacks:</strong> Initiating a chargeback or payment dispute with your bank or credit card issuer for a valid charge without first attempting to resolve the issue with our support team constitutes a breach of these Terms. We reserve the right to immediately suspend or permanently terminate your account and dispute the chargeback with your financial institution by providing transaction logs, IP addresses, and records of service delivery.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">2. Account Security & User Responsibility</h2>
        <p className="mb-4">
          You are 100% responsible for maintaining the confidentiality and security of your account credentials, passwords, API keys, and access tokens. You accept full legal and financial responsibility for all activities, API requests, and transactions that occur under your account. FIXDAI LLC is not liable for any loss, unauthorized access, data exposure, or fraudulent charges resulting from user negligence, compromised passwords, or stolen credentials. You agree to notify us immediately at <a href="mailto:support@doblaj.com" className="text-brand-400 underline">support@doblaj.com</a> upon discovering any breach of security.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">3. Service Level Agreement (SLA), Infrastructure & Liability Waivers</h2>
        <p className="mb-4">
          <strong>Third-Party Dependencies:</strong> The Doblaj platform relies on external third-party infrastructure, cloud GPU networks (e.g., Azure, RunPod), network providers (Cloudflare), and upstream AI language/speech model APIs (e.g., OpenRouter, Fish Speech, MiniMax).
        </p>
        <p className="mb-4">
          <strong>No Guaranteed Uptime:</strong> We do not guarantee 100% continuous, uninterrupted, or error-free service availability. FIXDAI LLC explicitly waives all financial and legal liability for service interruptions, AI model rate limits, API throttling, upstream model deprecation, network latency, system congestion, or cloud hardware failures beyond our reasonable control.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">4. Acceptable Use & Prohibited Conduct</h2>
        <p className="mb-4">You agree not to use the Services to:</p>
        <ul className="list-disc pl-6 mb-4">
          <li>Generate, dub, or distribute unauthorized voice clones, deceptive deepfakes, or copyrighted media without valid ownership or licensing rights.</li>
          <li>Violate any local, state, national, or international laws, or infringe on third-party intellectual property or privacy rights.</li>
          <li>Bypass security controls, rate limits, or perform reverse engineering of our platform or underlying AI pipeline.</li>
          <li>Upload viruses, malware, or conduct malicious scraping or DDoS attacks.</li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">5. Intellectual Property & DMCA Policy</h2>
        <p className="mb-4">
          All platform software, user interface design, branding, and proprietary algorithms are owned exclusively by FIXDAI LLC. You retain ownership of your original uploaded media and script inputs.
        </p>
        <p className="mb-4">
          If you believe content hosted on Doblaj infringes your copyright, submit a formal DMCA notice to our designated copyright agent at <a href="mailto:copyright@doblaj.com" className="text-brand-400 underline">copyright@doblaj.com</a>.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">6. Disclaimer of Warranties</h2>
        <p className="mb-4">
          THE SERVICES ARE PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS. FIXDAI LLC DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">7. Limitation of Liability</h2>
        <p className="mb-4">
          TO THE MAXIMUM EXTENT PERMITTED BY LAW, FIXDAI LLC SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, REVENUE, DATA, OR GOODWILL. IN NO EVENT SHALL FIXDAI LLC'S TOTAL AGGREGATE LIABILITY EXCEED THE GREATER OF ONE HUNDRED US DOLLARS ($100) OR THE AMOUNT PAID BY YOU TO FIXDAI LLC IN THE THREE (3) MONTHS PRECEDING THE CLAIM.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">8. Indemnification</h2>
        <p className="mb-4">
          You agree to defend, indemnify, and hold harmless FIXDAI LLC, its officers, directors, employees, and agents from any claims, liabilities, damages, losses, and expenses (including attorney fees) arising from your use of the Services, user content, or violation of these Terms.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">9. Governing Law & Dispute Resolution</h2>
        <p className="mb-4">
          <strong>Governing Law:</strong> These Terms are governed by and construed in accordance with the laws of the State of Texas, USA, without regard to conflict of law principles.
        </p>
        <p className="mb-4">
          <strong>Binding Arbitration & Class Action Waiver:</strong> Any dispute or claim arising out of or relating to these Terms shall be resolved through binding individual arbitration administered by the American Arbitration Association (AAA) in Austin, Texas, USA. YOU AGREE TO WAIVE ANY RIGHT TO PARTICIPATE IN A CLASS ACTION LAWSUIT OR CLASS-WIDE ARBITRATION.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">10. Contact Us</h2>
        <p className="mb-4">For questions regarding these Terms, contact:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Entity:</strong> FIXDAI LLC (d/b/a Doblaj)</li>
          <li><strong>Mailing Address:</strong> 3801 N Capital of Texas Hwy, Ste E240 #3958, Austin, TX 78746, Travis County, Texas, USA</li>
          <li><strong>Support Email:</strong> <a href="mailto:support@doblaj.com" className="text-brand-400 underline">support@doblaj.com</a></li>
          <li><strong>DMCA Email:</strong> <a href="mailto:copyright@doblaj.com" className="text-brand-400 underline">copyright@doblaj.com</a></li>
        </ul>
      </div>
    </div>
  );
}
