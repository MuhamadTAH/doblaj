import React from "react";

export default function RefundPolicyPage() {
  return (
    <div className="p-8 max-w-4xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Refund Policy</h1>
      
      <div className="prose prose-invert max-w-none">
        <p className="mb-4">
          <strong>Effective Date:</strong> July 28, 2026
        </p>

        <p className="mb-4">
          Thank you for choosing FIXDAI LLC, doing business as Doblaj ("we," "us," or "our"). This Refund Policy applies to all subscriptions, credit purchases, and services accessed via the Doblaj platform (doblaj.com).
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">1. Digital Fulfillment & Immediate Delivery</h2>
        <p className="mb-4">
          Doblaj is a B2B Software-as-a-Service (SaaS) platform that provisions high-performance cloud compute resources, GPU instances, and third-party AI model API access. When you subscribe or purchase credits, these digital resources are allocated and delivered to your account immediately. Because these hard compute costs are incurred by us instantaneously upon generation, our standard policy is that all sales are final.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">2. 7-Day Conditional Refund Window</h2>
        <p className="mb-4">
          We understand that you may need to evaluate whether the platform meets your requirements. We offer a conditional 7-day refund window for new subscription purchases, subject to the following strict criteria:
        </p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Timeframe:</strong> The refund request must be submitted within seven (7) calendar days of your initial subscription purchase.</li>
          <li><strong>Zero Usage:</strong> You must have consumed <strong>exactly zero (0) credits</strong> and initiated zero generation jobs (dubbing, text-to-speech, or otherwise) since the purchase. If you have processed any audio or video, you are no longer eligible for a refund, as compute costs have been permanently incurred.</li>
        </ul>
        <p className="mb-4">
          If you meet these criteria, please contact us at <a href="mailto:billing@doblaj.com" className="text-brand-400 underline">billing@doblaj.com</a> with your account details to request a refund. Approved refunds may take 5-10 business days to reflect on your original payment method.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">3. Non-Refundable Scenarios</h2>
        <p className="mb-4">Refunds will <strong>not</strong> be granted under any of the following circumstances:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Usage:</strong> Any portion of the purchased credits or subscription allocation has been used.</li>
          <li><strong>Partial Periods:</strong> You wish to cancel your subscription in the middle of a billing cycle (you will retain access until the end of the paid period, but no prorated refund will be issued).</li>
          <li><strong>Auto-Renewals:</strong> You forgot to cancel your subscription prior to the auto-renewal date. (You can cancel anytime via your Account Settings to prevent future charges).</li>
          <li><strong>Account Violation:</strong> Your account was suspended or terminated due to a violation of our Terms of Service (e.g., fraudulent activity, generating prohibited content, abuse of the platform).</li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">4. Chargebacks and Payment Disputes</h2>
        <p className="mb-4">
          We ask that you contact us first to resolve any billing issues. Initiating a fraudulent chargeback or payment dispute with your bank for a valid, non-refundable charge constitutes a breach of our Terms of Service. In the event of a chargeback, we will permanently suspend your account and provide the financial institution with comprehensive logs proving service delivery (including IP addresses, timestamps, and generation history).
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">5. Technical Errors</h2>
        <p className="mb-4">
          If you experience a technical billing error (such as a duplicate charge or being billed after a confirmed cancellation), please contact us immediately. We will investigate the issue and, if verified by our systems, issue a full refund for the erroneous charge.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">6. Contact Us</h2>
        <p className="mb-4">To request a refund under the 7-Day Conditional Refund Window or for billing inquiries, please contact our support team:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Email:</strong> <a href="mailto:billing@doblaj.com" className="text-brand-400 underline">billing@doblaj.com</a></li>
          <li><strong>Mailing Address:</strong> FIXDAI LLC, 3801 N Capital of Texas Hwy, Ste E240 #3958, Austin, TX 78746, USA</li>
        </ul>
      </div>
    </div>
  );
}
