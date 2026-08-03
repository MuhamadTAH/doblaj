import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@clerk/clerk-react";

export default function SoraniqLandingPage() {
  const { isSignedIn } = useAuth();
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(65);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [lang, setLang] = useState<"en" | "ckb" | "ar">("en");

  useEffect(() => {
    let interval: any;
    if (isPlaying) {
      interval = setInterval(() => {
        setProgress((prev) => (prev >= 110 ? 0 : prev + 2));
      }, 100);
    } else {
      setProgress(0);
    }
    return () => clearInterval(interval);
  }, [isPlaying]);

  const isRTL = lang === "ckb" || lang === "ar";

  const t = {
    en: {
      badge: "Dubbing Iraqi Arabic First Version",
      title: "Bring Your Stories to Every Iraqi Screen",
      subtitle:
        "Instant, dialect-accurate AI dubbing from Kurdish Sorani to Iraqi Arabic. Preserve original emotion, cadence, and timing with our synthetic precision engine.",
      ctaPrimary: "Upload Your First Video",
      ctaSecondary: "Watch Demo",
      featuresTitle: "Precision Engineered for Media",
      featuresSubtitle:
        "Built for professional creators who demand high-fidelity audio and cultural accuracy.",
      pricingTitle: "Transparent Pricing",
      pricingSubtitle: "Choose the plan that fits your production volume.",
      startTrial: "Start",
      dashboard: "Start",
    },
    ckb: {
      badge: "دۆبلاژی عەرەبی عێراقی وەشانی یەکەم",
      title: "چیرۆکەکانت بگەیەنە هەموو شاشەیەکی عێراقی",
      subtitle:
        "دۆبلاژی زیرەکی دەستکرد لە کوردی سۆرانییەوە بۆ عەرەبی عێراقی بە ڕاستیی شێوەزار و هەستی ڕەسەن.",
      ctaPrimary: "یەکەم ڤیدیۆت باربکە",
      ctaSecondary: "سەیری دیمۆ بکە",
      featuresTitle: "تایبەتمەندییە دروستکراوەکان بۆ میدیا",
      featuresSubtitle: "دروستکراوە بۆ دروستکەرانی ناوەڕۆک کە داوای بەرزیی کواڵێتی دەنگ دەکەن.",
      pricingTitle: "نرخی ئاشکرا و گونجاو",
      pricingSubtitle: "ئەو پلانە هەڵبژێره کە گونجاوە لەگەڵ بڕی بەرهەمهێنانت.",
      startTrial: "دەستپێکردن",
      dashboard: "داشبۆرد",
    },
    ar: {
      badge: "دبلجة اللهجة العراقية الإصدار الأول",
      title: "انقل قصصك إلى كل شاشة عراقية",
      subtitle:
        "دبلجة فورية بالذكاء الاصطناعي من الكردية السورانية إلى اللهجة العراقية بدقة وبدون فقدان المشاعر والسرعة الأصلية.",
      ctaPrimary: "ارفع أول فيديو",
      ctaSecondary: "شاهد العرض التجريبي",
      featuresTitle: "دقة متناهية لصناع المحتوى",
      featuresSubtitle: "صُمم خصيصاً للمحترفين الذين يبحثون عن أعلى جودة صوتية ودقة ثقافة محلية.",
      pricingTitle: "أسعار واضحة ومناسبة",
      pricingSubtitle: "اختر الخطة المناسبة لحجم إنتاجك الصوتي والفيديو.",
      startTrial: "ابدأ",
      dashboard: "لوحة التحكم",
    },
  }[lang];

  return (
    <div
      dir={isRTL ? "rtl" : "ltr"}
      className="min-h-screen bg-[#0a0a0b] text-[#cfcfd3] font-sans antialiased selection:bg-[#38bdf8]/20 selection:text-[#38bdf8]"
    >
      {/* TopNavBar */}
      <nav className="fixed top-0 w-full z-50 bg-[#0a0a0b]/80 backdrop-blur-xl border-b border-[rgba(255,255,255,0.06)] shadow-sm transition-all duration-300">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-10 flex justify-between items-center h-20">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#38bdf8] to-[#1a237e] p-0.5 flex items-center justify-center shadow-lg group-hover:scale-105 transition-transform">
              <div className="w-full h-full bg-[#0a0a0b] rounded-[7px] flex items-center justify-center">
                <span className="text-[#38bdf8] font-bold text-xl tracking-tighter">DB</span>
              </div>
            </div>
            <span className="text-2xl font-bold text-[#fafafa] tracking-tight group-hover:opacity-90 transition-opacity">
              Doblaj
            </span>
          </Link>

          <div className="hidden md:flex items-center gap-8 text-sm font-medium">
            <a href="#use-cases" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">
              Features
            </a>
            <a href="#how-it-works" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">
              How it Works
            </a>
            <a href="#pricing" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">
              Pricing
            </a>
          </div>

          <div className="hidden md:flex items-center gap-4">
            <div className="flex items-center bg-[#111114] border border-[rgba(255,255,255,0.08)] rounded-lg p-1 text-xs text-[#cfcfd3]">
              <button
                onClick={() => setLang("en")}
                className={`px-2 py-1 rounded font-medium ${lang === "en" ? "bg-[#38bdf8] text-[#0a0a0b]" : ""}`}
              >
                EN
              </button>
              <button
                onClick={() => setLang("ckb")}
                className={`px-2 py-1 rounded font-medium ${lang === "ckb" ? "bg-[#38bdf8] text-[#0a0a0b]" : ""}`}
              >
                کوردی
              </button>
              <button
                onClick={() => setLang("ar")}
                className={`px-2 py-1 rounded font-medium ${lang === "ar" ? "bg-[#38bdf8] text-[#0a0a0b]" : ""}`}
              >
                عربي
              </button>
            </div>

            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="inline-flex items-center justify-center px-6 py-2.5 rounded-lg bg-[#38bdf8] text-[#0a0a0b] text-sm font-semibold hover:opacity-90 transition-all shadow-sm"
            >
              {isSignedIn ? t.dashboard : t.startTrial}
            </Link>
          </div>

          <button
            onClick={() => setMobileMenu(!mobileMenu)}
            aria-label="Toggle menu"
            className="md:hidden text-[#cfcfd3] hover:text-[#38bdf8] p-2"
          >
            <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>

        {mobileMenu && (
          <div className="md:hidden bg-[#0a0a0b] border-b border-[rgba(255,255,255,0.08)] px-6 py-6 space-y-4">
            <a href="#use-cases" className="block text-base font-medium text-[#cfcfd3]">
              Features
            </a>
            <a href="#how-it-works" className="block text-base font-medium text-[#cfcfd3]">
              How it Works
            </a>
            <a href="#pricing" className="block text-base font-medium text-[#cfcfd3]">
              Pricing
            </a>
            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="block w-full text-center px-6 py-3 rounded-lg bg-[#38bdf8] text-[#0a0a0b] font-semibold text-sm"
            >
              {isSignedIn ? t.dashboard : t.startTrial}
            </Link>
          </div>
        )}
      </nav>

      {/* Hero Section */}
      <main className="pt-24 pb-16">
        <section className="relative overflow-hidden pt-12 pb-24 lg:pt-24 lg:pb-32 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-24 items-center">
            <div className="space-y-8 max-w-2xl">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#38bdf8]/10 border border-[#38bdf8]/30 text-[#38bdf8] font-mono text-xs sm:text-sm">
                <span className="w-2 h-2 rounded-full bg-[#38bdf8] animate-pulse"></span>
                {t.badge}
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold text-[#fafafa] tracking-tight leading-[1.15]">
                {t.title}
              </h1>

              <p className="text-lg sm:text-xl text-[#cfcfd3] leading-relaxed">
                {t.subtitle}
              </p>

              <div className="flex flex-col sm:flex-row gap-4 pt-2">
                <Link
                  to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
                  className="inline-flex items-center justify-center px-8 py-4 rounded-xl bg-[#38bdf8] text-[#0a0a0b] font-semibold text-base hover:opacity-90 transition-all shadow-lg"
                >
                  {t.ctaPrimary}
                </Link>
              </div>
            </div>

            {/* Faux UI Overlay Card - Mind Map */}
            <div className="relative w-full aspect-[4/3] rounded-2xl overflow-hidden shadow-2xl border border-[rgba(255,255,255,0.08)] bg-[#111114] p-8 flex flex-col justify-between">
              <div className="flex justify-between items-center z-10">
                <span className="text-xs font-mono text-[#38bdf8] bg-[#38bdf8]/10 border border-[#38bdf8]/20 px-3 py-1 rounded-full">
                  AI Pipeline
                </span>
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80"></span>
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
                </div>
              </div>

              <div className="flex-1 flex items-center justify-center">
                <div className="relative w-full max-w-sm flex flex-col gap-6">
                  {/* Step 1 */}
                  <div className={`relative z-10 flex items-center gap-4 p-4 rounded-xl border transition-all duration-500 ${isPlaying && progress > 5 ? 'bg-[#38bdf8]/10 border-[#38bdf8]/50 shadow-[0_0_20px_rgba(56,189,248,0.2)]' : 'bg-[#0a0a0b] border-[rgba(255,255,255,0.05)] opacity-60'}`}>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold transition-colors ${isPlaying && progress > 5 ? 'bg-[#38bdf8] text-[#0a0a0b]' : 'bg-[#111114] text-[#cfcfd3]'}`}>
                      1
                    </div>
                    <div>
                      <h4 className="text-[#fafafa] font-bold text-sm">Upload Video</h4>
                      <p className="text-[#cfcfd3] text-xs">Original Kurdish Sorani video</p>
                    </div>
                  </div>

                  {/* Connecting Line 1 */}
                  <div className="absolute left-[34px] top-14 w-0.5 h-6 bg-[rgba(255,255,255,0.05)] z-0">
                    <div className="w-full bg-[#38bdf8] transition-all duration-500 ease-linear" style={{ height: isPlaying ? (progress > 30 ? '100%' : progress > 5 ? `${(progress - 5) * 4}%` : '0%') : '0%' }} />
                  </div>

                  {/* Step 2 */}
                  <div className={`relative z-10 flex items-center gap-4 p-4 rounded-xl border transition-all duration-500 ${isPlaying && progress > 40 ? 'bg-[#38bdf8]/10 border-[#38bdf8]/50 shadow-[0_0_20px_rgba(56,189,248,0.2)]' : 'bg-[#0a0a0b] border-[rgba(255,255,255,0.05)] opacity-60'}`}>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold transition-colors ${isPlaying && progress > 40 ? 'bg-[#38bdf8] text-[#0a0a0b]' : 'bg-[#111114] text-[#cfcfd3]'}`}>
                      2
                    </div>
                    <div>
                      <h4 className="text-[#fafafa] font-bold text-sm">Dubbing Iraqi Arabic</h4>
                      <p className="text-[#cfcfd3] text-xs">AI Translation & Sync</p>
                    </div>
                  </div>

                  {/* Connecting Line 2 */}
                  <div className="absolute left-[34px] top-[136px] w-0.5 h-6 bg-[rgba(255,255,255,0.05)] z-0 hidden sm:block">
                    <div className="w-full bg-[#38bdf8] transition-all duration-500 ease-linear" style={{ height: isPlaying ? (progress > 65 ? '100%' : progress > 40 ? `${(progress - 40) * 4}%` : '0%') : '0%' }} />
                  </div>
                  <div className="absolute left-[34px] top-[148px] w-0.5 h-6 bg-[rgba(255,255,255,0.05)] z-0 sm:hidden">
                    <div className="w-full bg-[#38bdf8] transition-all duration-500 ease-linear" style={{ height: isPlaying ? (progress > 65 ? '100%' : progress > 40 ? `${(progress - 40) * 4}%` : '0%') : '0%' }} />
                  </div>

                  {/* Step 3 */}
                  <div className={`relative z-10 flex items-center gap-4 p-4 rounded-xl border transition-all duration-500 ${isPlaying && progress > 75 ? 'bg-[#38bdf8]/10 border-[#38bdf8]/50 shadow-[0_0_20px_rgba(56,189,248,0.2)]' : 'bg-[#0a0a0b] border-[rgba(255,255,255,0.05)] opacity-60'}`}>
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold transition-colors ${isPlaying && progress > 75 ? 'bg-[#38bdf8] text-[#0a0a0b]' : 'bg-[#111114] text-[#cfcfd3]'}`}>
                      3
                    </div>
                    <div>
                      <h4 className="text-[#fafafa] font-bold text-sm">Download</h4>
                      <p className="text-[#cfcfd3] text-xs">Ready for broadcast</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-[#0a0a0b]/90 backdrop-blur-md border border-[rgba(255,255,255,0.08)] rounded-xl p-4 flex items-center justify-between shadow-xl">
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setIsPlaying(!isPlaying)}
                    className="w-10 h-10 rounded-full bg-[#38bdf8] text-[#0a0a0b] flex items-center justify-center hover:scale-105 transition-transform"
                  >
                    {isPlaying ? "⏸" : "▶"}
                  </button>
                  <div>
                    <div className="text-xs font-medium text-[#fafafa] mb-1">
                      {isPlaying ? (progress > 75 ? "Complete!" : progress > 40 ? "Processing Dubbing..." : "Uploading...") : "Ready to Start"}
                    </div>
                    <div className="w-36 h-1.5 bg-[#111114] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[#38bdf8] rounded-full transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 text-xs font-mono">
                  <span className="px-2 py-1 rounded bg-[#111114] text-[#cfcfd3]">Sorani</span>
                  <span className="text-[#38bdf8]">→</span>
                  <span className="px-2 py-1 rounded bg-[#38bdf8]/10 text-[#38bdf8] font-semibold">Iraqi</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* How it Works */}
        <section className="py-24 px-4 sm:px-6 lg:px-10 bg-[#0a0a0b]" id="how-it-works">
          <div className="max-w-7xl mx-auto">
            <div className="text-center max-w-2xl mx-auto mb-16 space-y-4">
              <h2 className="text-3xl sm:text-4xl font-bold text-[#fafafa]">Seamless Translation Pipeline</h2>
              <p className="text-base sm:text-lg text-[#cfcfd3]">
                Three simple steps to transform your content for a wider audience.
              </p>
            </div>
            <div className="grid md:grid-cols-3 gap-8">
              <div className="bg-[#111114] rounded-2xl p-8 border border-[rgba(255,255,255,0.06)] shadow-lg">
                <div className="w-14 h-14 rounded-xl bg-[#0a0a0b] flex items-center justify-center mb-6 text-[#38bdf8] font-bold text-xl">
                  1
                </div>
                <h3 className="text-xl font-bold text-[#fafafa] mb-3">1. Upload Video</h3>
                <p className="text-sm text-[#cfcfd3]">Upload raw Kurdish Sorani video up to 4K resolution.</p>
              </div>
              <div className="bg-[#111114] rounded-2xl p-8 border border-[rgba(255,255,255,0.06)] shadow-lg">
                <div className="w-14 h-14 rounded-xl bg-[#0a0a0b] flex items-center justify-center mb-6 text-[#38bdf8] font-bold text-xl">
                  2
                </div>
                <h3 className="text-xl font-bold text-[#fafafa] mb-3">2. AI Processing</h3>
                <p className="text-sm text-[#cfcfd3]">Translates nuance and synthesizes natural Iraqi Arabic.</p>
              </div>
              <div className="bg-[#111114] rounded-2xl p-8 border border-[rgba(255,255,255,0.06)] shadow-lg">
                <div className="w-14 h-14 rounded-xl bg-[#0a0a0b] flex items-center justify-center mb-6 text-[#38bdf8] font-bold text-xl">
                  3
                </div>
                <h3 className="text-xl font-bold text-[#fafafa] mb-3">3. Download</h3>
                <p className="text-sm text-[#cfcfd3]">Receive perfectly synced high-quality video ready for broadcast.</p>
              </div>
            </div>
          </div>
        </section>

        
      </main>

      {/* Use Cases Section */}
      <section className="py-24 px-4 sm:px-6 lg:px-10 bg-[#111114] border-y border-[rgba(255,255,255,0.06)]" id="use-cases">
        <div className="max-w-7xl mx-auto">
          <div className="text-center max-w-2xl mx-auto mb-16 space-y-4">
            <h2 className="text-3xl sm:text-4xl font-bold text-[#fafafa]">Who is Doblaj For?</h2>
            <p className="text-base sm:text-lg text-[#cfcfd3]">
              Empowering creators and businesses to break language barriers.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            <div className="bg-[#0a0a0b] rounded-2xl p-8 border border-[rgba(255,255,255,0.04)] shadow-sm hover:border-[#38bdf8]/30 transition-all">
              <h3 className="text-xl font-bold text-[#fafafa] mb-3 flex items-center gap-3">
                <span className="text-2xl">🎥</span> Content Creators
              </h3>
              <p className="text-sm text-[#cfcfd3] leading-relaxed">
                Grow your audience exponentially by dubbing your YouTube, TikTok, and Instagram videos into flawless Iraqi Arabic without losing your unique voice.
              </p>
            </div>
            <div className="bg-[#0a0a0b] rounded-2xl p-8 border border-[rgba(255,255,255,0.04)] shadow-sm hover:border-[#38bdf8]/30 transition-all">
              <h3 className="text-xl font-bold text-[#fafafa] mb-3 flex items-center gap-3">
                <span className="text-2xl">📰</span> News & Media
              </h3>
              <p className="text-sm text-[#cfcfd3] leading-relaxed">
                Broadcast breaking news across Kurdistan and Iraq simultaneously. Maintain journalistic integrity with culturally accurate dialect translation.
              </p>
            </div>
            <div className="bg-[#0a0a0b] rounded-2xl p-8 border border-[rgba(255,255,255,0.04)] shadow-sm hover:border-[#38bdf8]/30 transition-all">
              <h3 className="text-xl font-bold text-[#fafafa] mb-3 flex items-center gap-3">
                <span className="text-2xl">🏢</span> Marketing Agencies
              </h3>
              <p className="text-sm text-[#cfcfd3] leading-relaxed">
                Run unified campaigns across different regions. Save thousands on voice actors while keeping your brand messaging consistent in every dialect.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section className="py-24 px-4 sm:px-6 lg:px-10 bg-[#0a0a0b]" id="faq">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16 space-y-4">
            <h2 className="text-3xl sm:text-4xl font-bold text-[#fafafa]">Frequently Asked Questions</h2>
          </div>
          <div className="space-y-6">
            <div className="bg-[#111114] rounded-xl p-6 border border-[rgba(255,255,255,0.06)]">
              <h4 className="text-lg font-bold text-[#fafafa] mb-2">How long does the dubbing process take?</h4>
              <p className="text-sm text-[#cfcfd3]">
                Our AI processes video at roughly 1/3 of the real-time length. A 3-minute video typically takes about 1 minute to translate, synthesize, and sync.
              </p>
            </div>
            <div className="bg-[#111114] rounded-xl p-6 border border-[rgba(255,255,255,0.06)]">
              <h4 className="text-lg font-bold text-[#fafafa] mb-2">Does it support multiple speakers?</h4>
              <p className="text-sm text-[#cfcfd3]">
                Yes, our advanced pipeline automatically detects multiple speakers in your video and assigns distinct AI voices to each person to maintain conversational flow.
              </p>
            </div>
            <div className="bg-[#111114] rounded-xl p-6 border border-[rgba(255,255,255,0.06)]">
              <h4 className="text-lg font-bold text-[#fafafa] mb-2">Can I keep the original background music and sound effects?</h4>
              <p className="text-sm text-[#cfcfd3]">
                Absolutely. Our AI isolates the vocal track, translates and replaces it, then seamlessly mixes it back with your original background audio.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing */}
        <section className="py-24 px-4 sm:px-6 lg:px-10 bg-[#0a0a0b]" id="pricing">
          <div className="max-w-7xl mx-auto text-center">
            <h2 className="text-3xl sm:text-4xl font-bold text-[#fafafa] mb-4">{t.pricingTitle}</h2>
            <p className="text-base sm:text-lg text-[#cfcfd3] mb-12">{t.pricingSubtitle}</p>
            <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
              <div className="bg-[#111114] rounded-2xl p-8 border border-[rgba(255,255,255,0.06)] text-left flex flex-col justify-between">
                <div>
                  <h3 className="text-xl font-bold text-[#fafafa] mb-2">Starter</h3>
                  <div className="text-4xl font-extrabold text-[#fafafa] mb-4">$10 <span className="text-sm text-[#cfcfd3]">/mo</span></div>
                  <p className="text-xs text-[#cfcfd3] mb-4">5 Minutes ($2.00/min)</p>
                  <ul className="text-sm text-[#cfcfd3] space-y-3 mb-6">
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Standard processing speed</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> 1080p export resolution</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Basic voices included</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Up to 2 speakers</li>
                  </ul>
                </div>
                <Link to={isSignedIn ? "/pricing?plan=starter" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=starter')}`} className="w-full py-3 rounded-xl border border-[rgba(255,255,255,0.08)] text-center text-sm font-semibold text-[#fafafa] hover:bg-[rgba(255,255,255,0.02)] transition-colors block">
                  Get 5 Minutes
                </Link>
              </div>
              <div className="bg-[#111114] rounded-2xl p-8 border border-[#38bdf8]/40 text-left flex flex-col justify-between relative bg-gradient-to-b from-[#111114] to-[#1a237e]/20 shadow-[0_0_30px_rgba(56,189,248,0.1)]">
                <div className="absolute top-0 right-8 -translate-y-1/2 px-3 py-1 bg-[#38bdf8] text-[#0a0a0b] text-xs font-bold uppercase rounded-full">Most Popular</div>
                <div>
                  <h3 className="text-xl font-bold text-[#fafafa] mb-2">Pro</h3>
                  <div className="text-4xl font-extrabold text-[#fafafa] mb-4">$20 <span className="text-sm text-[#cfcfd3]">/mo</span></div>
                  <p className="text-xs text-[#cfcfd3] mb-4">15 Minutes ($1.33/min)</p>
                  <ul className="text-sm text-[#cfcfd3] space-y-3 mb-6">
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Priority processing speed</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> 4K export resolution</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Premium emotional voices</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Up to 5 speakers</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Advanced timeline editor</li>
                  </ul>
                </div>
                <Link to={isSignedIn ? "/pricing?plan=pro" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=pro')}`} className="w-full py-3 rounded-xl bg-[#38bdf8] text-[#0a0a0b] text-center text-sm font-bold hover:bg-[#38bdf8]/90 transition-colors block shadow-lg">
                  Get 15 Minutes
                </Link>
              </div>
              <div className="bg-[#111114] rounded-2xl p-8 border border-[rgba(255,255,255,0.06)] text-left flex flex-col justify-between">
                <div>
                  <h3 className="text-xl font-bold text-[#fafafa] mb-2">Creator</h3>
                  <div className="text-4xl font-extrabold text-[#fafafa] mb-4">$99 <span className="text-sm text-[#cfcfd3]">/mo</span></div>
                  <p className="text-xs text-[#cfcfd3] mb-4">120 Minutes ($0.82/min)</p>
                  <ul className="text-sm text-[#cfcfd3] space-y-3 mb-6">
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Highest priority queue</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> 4K lossless export</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> All premium voices included</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Unlimited speakers</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> Custom voice cloning</li>
                    <li className="flex items-center gap-2"><span className="text-[#38bdf8]">✓</span> API Access</li>
                  </ul>
                </div>
                <Link to={isSignedIn ? "/pricing?plan=creator" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=creator')}`} className="w-full py-3 rounded-xl border border-[rgba(255,255,255,0.08)] text-center text-sm font-semibold text-[#fafafa] hover:bg-[rgba(255,255,255,0.02)] transition-colors block">
                  Get 120 Minutes
                </Link>
              </div>
            </div>
          </div>
        </section>

      <footer className="bg-[#0a0a0b] border-t border-[rgba(255,255,255,0.06)] w-full py-16 px-4 sm:px-6 lg:px-10" id="contact">
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-4 gap-12">
          <div className="col-span-1 md:col-span-2 space-y-4 pr-8">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#38bdf8] to-[#1a237e] p-0.5 flex items-center justify-center shadow-lg">
                <div className="w-full h-full bg-[#0a0a0b] rounded-[6px] flex items-center justify-center">
                  <span className="text-[#38bdf8] font-bold text-sm tracking-tighter">DB</span>
                </div>
              </div>
              <span className="text-xl font-bold text-[#fafafa]">Doblaj</span>
            </div>
            <p className="text-sm sm:text-base text-[#cfcfd3] max-w-sm leading-relaxed">
              Synthesizing communication across dialects. Precision AI dubbing for Kurdish and Arabic media.
            </p>
            <div className="pt-4 text-xs text-[#cfcfd3] space-y-1">
              <p className="font-semibold text-white">FIXDAI LLC (d/b/a Doblaj)</p>
              <p>3801 N Capital of Texas Hwy, Ste E240 #3958</p>
              <p>Austin, TX 78746, Travis County, Texas, USA</p>
            </div>
            <div className="pt-2 text-xs text-[#cfcfd3] space-y-1">
              <p>Support: <a href="mailto:support@doblaj.com" className="text-[#38bdf8] hover:underline">support@doblaj.com</a></p>
              <p>DMCA: <a href="mailto:copyright@doblaj.com" className="text-[#38bdf8] hover:underline">copyright@doblaj.com</a></p>
            </div>
            <p className="text-xs text-[rgba(255,255,255,0.4)] pt-4">© 2026 FIXDAI LLC d/b/a Doblaj. All rights reserved.</p>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Product</h4>
            <ul className="space-y-3 text-sm">
              <li>
                <a href="#pricing" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">Pricing</a>
              </li>
              <li>
                <a href="#" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">API Documentation</a>
              </li>
              <li>
                <a href="#" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">Help Center</a>
              </li>
            </ul>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Legal & Social</h4>
            <ul className="space-y-3 text-sm">
              <li>
                <Link to="/privacy" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">Privacy Policy</Link>
              </li>
              <li>
                <Link to="/terms" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">Terms of Service</Link>
              </li>
              <li>
                <Link to="/refund-policy" className="text-[#cfcfd3] hover:text-[#38bdf8] transition-colors">Refund Policy</Link>
              </li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  );
}
