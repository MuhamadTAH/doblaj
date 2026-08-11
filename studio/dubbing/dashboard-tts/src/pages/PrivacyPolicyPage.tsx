import React from "react";

export default function PrivacyPolicyPage() {
  return (
    <div className="p-8 max-w-4xl mx-auto text-white">
      <h1 className="text-3xl font-bold mb-6">Privacy Policy</h1>
      
      <div className="prose prose-invert max-w-none">
        <p className="mb-4">
          <strong>Effective Date:</strong> July 28, 2026
        </p>

        <p className="mb-4">
          This Privacy Policy explains how FIXDAI LLC, doing business as Doblaj (operating the website doblaj.com) ("we," "us," or "our"), collects, uses, discloses, and safeguards your personal data when you visit our website, use our B2B SaaS platform, or interact with our services (collectively, the "Services"). We will notify users of material changes to this Privacy Policy and obtain renewed consent where processing relies on consent.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">1. Data We Collect and Processing Purposes</h2>
        <p className="mb-4">We process the following categories of personal and account data to deliver and improve our Services:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Account Information:</strong> Name, business email address, hashed credentials, and authentication tokens. Lawful basis: Performance of a contract.</li>
          <li><strong>Transaction & Billing Data:</strong> Payment transaction metadata, billing addresses, invoice history, and subscription status (processed via third-party processors). Lawful basis: Performance of a contract and compliance with legal/tax obligations.</li>
          <li><strong>Technical & Usage Data:</strong> IP addresses, browser types, device diagnostics, API request metrics, and system interaction logs. Lawful basis: Legitimate business interests (security, fraud prevention, service optimization).</li>
          <li><strong>User Content & Media Assets:</strong> Video files, audio recordings, script text, and generated translations uploaded or generated through the platform. Lawful basis: Performance of a contract.</li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">2. Meta Platforms Technologies User Data Disclosure</h2>
        <p className="mb-4">
          If you connect or integrate your Meta account (including Facebook or Instagram) with Doblaj, we process specific "Meta Platforms Technologies User Data."
        </p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Meta Data Collected:</strong> Public profile information, account identifiers, connected page details, user access tokens, and comment/message content authorized via Meta OAuth permissions.</li>
          <li><strong>Processing Purpose:</strong> Meta User Data is processed exclusively to enable authorized platform functionality, such as automated comment replies, publishing video/audio content, and streamlining customer interactions across connected Meta channels.</li>
          <li><strong>Data Handling Restrictions:</strong> We do not sell, share, transfer, or use Meta User Data for advertising, profiling, or third-party marketing purposes.</li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">3. Data Deletion & Access Revocation (Meta & Platform Data)</h2>
        <p className="mb-4">
          We provide clear, self-serve paths for revoking access and requesting complete data deletion in compliance with GDPR, CCPA, and Meta Developer Data Use Policies:
        </p>
        <ul className="list-disc pl-6 mb-4">
          <li>
            <strong>Revoking Meta Access:</strong> You can revoke Doblaj's access to your Meta account at any time by navigating to your <em>Facebook Settings & Privacy &gt; Settings &gt; Apps and Websites</em> (or Instagram Account Settings), selecting <strong>Doblaj</strong>, and clicking <strong>Remove</strong>.
          </li>
          <li>
            <strong>Doblaj Platform Data Deletion:</strong> Users can submit a verifiable data deletion request at any time directly within the Doblaj platform by visiting <code>/tts/settings</code> (Account Settings &gt; Danger Zone) and confirming account deletion with their password. Alternatively, submit a written request to <a href="mailto:privacy@doblaj.com" className="text-brand-400 underline">privacy@doblaj.com</a>.
          </li>
          <li>
            <strong>Deletion Execution:</strong> Upon receiving a deletion request, user account data and associated media assets are purged from active systems within 30 days. Minimal transaction records are retained for 7 years to comply with tax and audit laws, and system security logs are retained for 90 days.
          </li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">4. Third-Party Infrastructure & Sub-processors</h2>
        <p className="mb-4">To deliver AI-powered audio/video processing and SaaS infrastructure, we utilize trusted third-party sub-processors:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Cloud & Compute Providers:</strong> Microsoft Azure, RunPod, and Cloudflare (hosting, storage, network protection, GPU computing).</li>
          <li><strong>AI Models & Gateway Providers:</strong> OpenRouter, Fish Speech, MiniMax, AssemblyAI, Deepgram (AI inference, speech-to-text, translation, and TTS models).</li>
          <li><strong>Payment Processors:</strong> Wayl (secure local billing, tokenized payment processing).</li>
          <li><strong>Communication & Analytics:</strong> Resend, Chatwoot, and Google Analytics (transactional emails, customer messaging, web analytics).</li>
        </ul>

        <h2 className="text-2xl font-semibold mt-8 mb-4">5. Cookies and Global Privacy Control (GPC)</h2>
        <p className="mb-4">
          We use essential cookies for session management and authentication, and consent-based cookies for analytics. We honor the Global Privacy Control (GPC) signal broadcast by web browsers. We do not sell or share personal data for cross-context behavioral advertising.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">6. Children's Privacy</h2>
        <p className="mb-4">
          Our Services are strictly B2B software not intended for individuals under 18 years of age. We do not knowingly collect personal data from minors.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">7. International Data Transfers & Security</h2>
        <p className="mb-4">
          Data is processed and hosted in secure data centers in the United States and global edge locations. For transfers outside the EEA or UK, we rely on Standard Contractual Clauses (SCCs) and adequacy decisions. We employ industry-standard encryption, tokenization, and access controls.
        </p>

        <h2 className="text-2xl font-semibold mt-8 mb-4">8. Contact Information</h2>
        <p className="mb-4">For privacy inquiries, Data Protection Officer communications, or compliance requests, contact:</p>
        <ul className="list-disc pl-6 mb-4">
          <li><strong>Legal Entity:</strong> FIXDAI LLC (d/b/a Doblaj)</li>
          <li><strong>Mailing Address:</strong> 3801 N Capital of Texas Hwy, Ste E240 #3958, Austin, TX 78746, Travis County, Texas, USA</li>
          <li><strong>Privacy & Support Email:</strong> <a href="mailto:privacy@doblaj.com" className="text-brand-400 underline">privacy@doblaj.com</a> / <a href="mailto:support@doblaj.com" className="text-brand-400 underline">support@doblaj.com</a></li>
        </ul>
      </div>
    </div>
  );
}
