import re

with open("src/pages/SoraniqLandingPage.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update translations
content = content.replace('"New: Iraqi Arabic Model V2.0"', '"Dubbing Iraqi Arabic First Version"')
content = content.replace('"نوێ: مۆدێلی عەرەبی عێراقی ڤێرژنی ٢.٠"', '"دۆبلاژی عەرەبی عێراقی وەشانی یەکەم"')
content = content.replace('"جديد: نموذج اللهجة العراقية V2.0"', '"دبلجة اللهجة العراقية الإصدار الأول"')
content = content.replace('dashboard: "Dashboard"', 'dashboard: "Start"')

# 2. Doblaj branding
content = content.replace('SoranIQ', 'Doblaj')
content = content.replace('SQ', 'DB')

# 3. Header Links #features -> #use-cases
content = content.replace('href="#features"', 'href="#use-cases"')

# 4. CTA Buttons
cta_buttons = """<Link
                  to={isSignedIn ? "/tts" : "/sign-up"}
                  className="inline-flex items-center justify-center px-8 py-4 rounded-xl bg-[#38bdf8] text-[#0a0a0b] font-semibold text-base hover:opacity-90 transition-all shadow-lg"
                >
                  {t.ctaPrimary}
                </Link>
                <button
                  onClick={() => setIsPlaying(!isPlaying)}
                  className="inline-flex items-center justify-center px-8 py-4 rounded-xl bg-transparent border border-[rgba(255,255,255,0.08)] text-[#fafafa] font-semibold text-base hover:border-[#38bdf8] transition-all"
                >
                  {t.ctaSecondary}
                </button>"""

new_cta = """<Link
                  to="/dubbing"
                  className="inline-flex items-center justify-center px-8 py-4 rounded-xl bg-[#38bdf8] text-[#0a0a0b] font-semibold text-base hover:opacity-90 transition-all shadow-lg"
                >
                  {t.ctaPrimary}
                </Link>"""
content = content.replace(cta_buttons, new_cta)

# Fix pricing links to preserve redirect_url
pricing_starter = """<Link to="/pricing?plan=starter" """
content = content.replace(pricing_starter, """<Link to={isSignedIn ? "/pricing?plan=starter" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=starter')}`} """)
pricing_pro = """<Link to="/pricing?plan=pro" """
content = content.replace(pricing_pro, """<Link to={isSignedIn ? "/pricing?plan=pro" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=pro')}`} """)
pricing_creator = """<Link to="/pricing?plan=creator" """
content = content.replace(pricing_creator, """<Link to={isSignedIn ? "/pricing?plan=creator" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=creator')}`} """)

# Update navbar CTA link as well to use redirect_url
navbar_cta = """<Link
              to={isSignedIn ? "/tts" : "/sign-up"}
              className="inline-flex items-center justify-center px-6 py-2.5 rounded-lg bg-[#38bdf8] text-[#0a0a0b] text-sm font-semibold hover:opacity-90 transition-all shadow-sm"
            >"""
new_navbar_cta = """<Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="inline-flex items-center justify-center px-6 py-2.5 rounded-lg bg-[#38bdf8] text-[#0a0a0b] text-sm font-semibold hover:opacity-90 transition-all shadow-sm"
            >"""
content = content.replace(navbar_cta, new_navbar_cta)

mobile_cta = """<Link
              to={isSignedIn ? "/tts" : "/sign-up"}
              className="block w-full text-center px-6 py-3 rounded-lg bg-[#38bdf8] text-[#0a0a0b] font-semibold text-sm"
            >"""
new_mobile_cta = """<Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="block w-full text-center px-6 py-3 rounded-lg bg-[#38bdf8] text-[#0a0a0b] font-semibold text-sm"
            >"""
content = content.replace(mobile_cta, new_mobile_cta)


# 5. Move pricing below FAQ
pricing_regex = re.compile(r'\{\/\* Pricing \*\/\}.*?<\/section>', re.DOTALL)
pricing_match = pricing_regex.search(content)
if pricing_match:
    pricing_block = pricing_match.group(0)
    content = content.replace(pricing_block, "")
    
    faq_regex = re.compile(r'\{\/\* FAQ Section \*\/\}.*?<\/section>', re.DOTALL)
    faq_match = faq_regex.search(content)
    if faq_match:
        faq_block = faq_match.group(0)
        content = content.replace(faq_block, faq_block + "\n\n      " + pricing_block)

# 6. Faux UI block -> Mind map
faux_ui_start = content.find('{/* Faux UI Overlay Card */}')
faux_ui_end = content.find('</div>\n          </div>\n        </section>', faux_ui_start)

mind_map_ui = """{/* Faux UI Overlay Card - Mind Map */}
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
            </div>"""

content = content[:faux_ui_start] + mind_map_ui + content[faux_ui_end:]

# Fix progress speed in useEffect
use_effect_old = """  useEffect(() => {
    let interval: any;
    if (isPlaying) {
      interval = setInterval(() => {
        setProgress((prev) => (prev >= 100 ? 0 : prev + 2));
      }, 200);
    }
    return () => clearInterval(interval);
  }, [isPlaying]);"""

use_effect_new = """  useEffect(() => {
    let interval: any;
    if (isPlaying) {
      interval = setInterval(() => {
        setProgress((prev) => (prev >= 110 ? 0 : prev + 2));
      }, 100);
    } else {
      setProgress(0);
    }
    return () => clearInterval(interval);
  }, [isPlaying]);"""
content = content.replace(use_effect_old, use_effect_new)

# Footer address replacement
footer_start = content.find('<footer')
footer_left_col_start = content.find('<div className="col-span-1 md:col-span-2 space-y-4">', footer_start)
footer_left_col_end = content.find('<div className="col-span-1 space-y-4">', footer_left_col_start)

new_footer_left = """<div className="col-span-1 md:col-span-2 space-y-4 pr-8">
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
          """

content = content[:footer_left_col_start] + new_footer_left + content[footer_left_col_end:]

with open("src/pages/SoraniqLandingPage.tsx", "w", encoding="utf-8") as f:
    f.write(content)

print("Updated SoraniqLandingPage.tsx")
