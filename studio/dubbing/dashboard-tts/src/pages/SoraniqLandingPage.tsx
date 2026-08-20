import React, { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@clerk/clerk-react";

export default function SoraniqLandingPage() {
  const { isSignedIn } = useAuth();
  const navigate = useNavigate();
  const [lang, setLang] = useState<"en" | "ckb" | "ar">("ckb");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [whatsAppNumber, setWhatsAppNumber] = useState("");
  const [toastIndex, setToastIndex] = useState(0);
  const [showToast, setShowToast] = useState(true);

  // Live social proof toasts cycling every 9 seconds
  const liveNotifications = {
    en: [
      { text: "A fashion boutique on Salim St. just dubbed 3 reels into Iraqi Arabic.", time: "2 min ago" },
      { text: "A showroom in Mawlawi St. captured 14 tourist orders from Baghdad.", time: "5 min ago" },
      { text: "An electronics store in Saholaka converted a 2-minute Kurdish promo.", time: "8 min ago" },
      { text: "A perfume shop in Majidi Mall just linked their WhatsApp.", time: "11 min ago" },
    ],
    ckb: [
      { text: "دووکانێکی جلوبەرگ لە شەقامی سەلیم ٣ ڤیدیۆی کردە عەرەبی عێراقی.", time: "٢ خولەک لەمەوبەر" },
      { text: "پێشانگایەک لە شەقامی مەولەوی ١٤ داواکاریی گەشتیارانی بەغدای وەرگرت.", time: "٥ خولەک لەمەوبەر" },
      { text: "دووکانێکی مۆبایل لە سەهۆڵەکە ڕیکلامێکی ٢ خولەکیی سۆرانی گۆڕی بۆ عێراقی.", time: "٨ خولەک لەمەوبەر" },
      { text: "بۆنفرۆشێک لە مەجیدی مۆڵ وەتسئەپەکەی بەستەوە بە سیستەمەکە.", time: "١١ خولەک لەمەوبەر" },
    ],
    ar: [
      { text: "محل أزياء بشارع سالم دبلج ٣ فيديوهات للهجة العراقية الآن.", time: "منذ دقيقتين" },
      { text: "معرض بشارع مولوي استقبل ١٤ طلب من سياح بغداد.", time: "منذ ٥ دقائق" },
      { text: "محل إلكترونيات بالسهولكة حول إعلانه من الكردية إلى العراقية.", time: "منذ ٨ دقائق" },
      { text: "محل عطور بمجيدي مول ربط رقمه على الواتساب للبدء فوراً.", time: "منذ ١١ دقيقة" },
    ],
  }[lang];

  useEffect(() => {
    const interval = setInterval(() => {
      setShowToast(false);
      setTimeout(() => {
        setToastIndex((prev) => (prev + 1) % liveNotifications.length);
        setShowToast(true);
      }, 400);
    }, 9000);
    return () => clearInterval(interval);
  }, [liveNotifications.length]);

  const isRTL = lang === "ckb" || lang === "ar";

  const t = {
    en: {
      badge: "🚨 ATTENTION: SULAIMANIYAH & ERBIL RETAIL OWNERS",
      heroHeadlineStart: "The local market is frozen.",
      heroHeadlineHighlight: "The Arab tourists are spending billions of dinars.",
      heroHeadlineEnd: "Which market is your store talking to?",
      heroSub:
        "Stop waiting for delayed salaries. With our AI system, instantly dub your store's videos into Iraqi Arabic and turn the tourists walking past your door into real paying customers.",
      inputPlaceholder: "Enter WhatsApp number (+964 7XX...)",
      ctaPrimary: "Link My WhatsApp in 10 Seconds",
      ctaSubtext: "⚡ 100% Free Demo • No credit card required to test",
      
      splitLeftTitle: "(Your Store Right Now)",
      splitLeftStatus: "Cold & Silent",
      splitLeftItem1: "❌ Waiting for delayed local government salaries",
      splitLeftItem2: "❌ Over $10,000+ in unsold seasonal inventory piling up",
      splitLeftItem3: "❌ Arab tourists walk right past your door without noticing you",
      splitLeftMetric: "$0 Tourist Revenue",

      splitRightTitle: "(Your Store With Doblaj AI)",
      splitRightStatus: "Continuous Cash Flow",
      splitRightItem1: "✅ Kurdish videos instantly dubbed into fluent Iraqi dialect",
      splitRightItem2: "✅ Tourists see you on TikTok and come directly to your store",
      splitRightItem3: "✅ Daily sales to tourists from Baghdad and Basra",
      splitRightMetric: "+1,500,000 IQD Avg. Weekend Profit",
      splitBottomNote: "(Note: Just ONE sale to an Arab tourist covers the entire monthly cost of this system. The remaining 29 days are 100% pure profit for you).",

      painSectionTag: "TERRITORIAL ALERT",
      painHeadline: "While you sit on unsold inventory, your competitors are taking the tourist cash.",
      painBody:
        "While you are sitting on thousands of dollars in unsold stock, 14 other retail shops in Sulaymaniyah and Erbil are already using our AI to bring Arab tourists directly into their showrooms.",
      mapTitle: "Live Active Stores in Sulaymaniyah & Erbil",
      mapSubtitle: "Pulsing pins represent stores actively dubbing videos this week",
      
      pricingAnchor: "Hiring a human Arabic voice translator:",
      pricingAnchorOld: "$500 / month",
      pricingAnchorSave: "Save 96% with Doblaj AI",
      pricingTitle: "The Survival Pricing",
      pricingSubtitle: "One sale to an Arab tourist pays for an entire year of this software.",

      decoyTitle: "Decoy Starter",
      decoyPrice: "$15",
      decoyPeriod: "/mo",
      decoyLimit: "Strict Limit: 1 Single Video",
      decoyItem1: "Slow queue processing",
      decoyItem2: "Standard 720p export",
      decoyItem3: "Basic mechanical voice",
      decoyCta: "Get 1 Video ($15)",

      targetBadge: "🔥 MOST POPULAR — UNLIMITED EXPANSION",
      targetTitle: "Retail Growth Target",
      targetPrice: "$20",
      targetPeriod: "/mo",
      targetLimit: "Unlimited Videos (Up to 15 mins total)",
      targetItem1: "⚡ Priority instant processing",
      targetItem2: "✨ Premium authentic Iraqi dialect & emotion",
      targetItem3: "🎥 4K Ultra-HD export for Instagram & TikTok",
      targetItem4: "🗣️ Preserves original background music & room audio",
      targetMicroCopy: "💡 Costs less than the profit of selling ONE single t-shirt.",
      targetCta: "Claim $20 Unlimited Access Now",

      anchorTitle: "Commercial Agency",
      anchorPrice: "$99",
      anchorPeriod: "/mo",
      anchorLimit: "120 Minutes Multi-Branch Power",
      anchorItem1: "Dedicated VIP processing queue",
      anchorItem2: "Unlimited multi-speaker detection",
      anchorItem3: "Custom voice cloning for your staff",
      anchorItem4: "Direct API + 24/7 priority support",
      anchorCta: "Get Agency Tier ($99)",

      paymentTrust: "🔒 Pay securely with FastPay, FIB, ZainCash, Visa or Mastercard.",

      faqTitle: "Frequently Answered Objections",
      faqSubtitle: "Read before your competitor on your street takes your tourist customers.",

      faq1Q: "Can't I just put free Arabic subtitles (text) on my Kurdish videos?",
      faq1A:
        "Nobody walking through a noisy bazaar or rapidly scrolling TikTok stops to read small text subtitles while shopping. Tourists buy with their ears when they hear a friendly, authentic Iraqi voice greeting them directly in their own Baghdad dialect. Subtitles get skipped in 0.5 seconds; native audio dubbing turns scrolling tourists into paying in-store customers instantly.",

      faq2Q: "I'm just a shopkeeper, not a tech expert. Is this too complicated for me?",
      faq2A:
        "You don't need to be a software engineer—you're a smart business owner. If you know how to send a video on WhatsApp or post a story on Instagram, you can use Doblaj in 10 seconds. You simply upload your video, our AI speaks it in natural Iraqi Arabic, and you post it. It was built specifically for busy Kurdish shop owners who want sales, not tech headaches.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • Austin, TX, USA",
      navFeatures: "The Advantage",
      navMap: "Active Map",
      navPricing: "Pricing",
      navFaq: "FAQ",
      navLogin: "Dashboard",
      navStart: "Start Now",
    },
    ckb: {
      badge: "🚨 ئاگاداری: بۆ خاوەن دووکان و پێشانگاکانی سلێمانی و هەولێر",
      heroHeadlineStart: "بازاڕی خۆماڵی سستە و بێ پارەیە.",
      heroHeadlineHighlight: "گەشتیارە عەرەبەکان ملیاران دینار خەرج دەکەن.",
      heroHeadlineEnd: "دووکانەکەت قسە بۆ کام بازاڕ دەکات؟",
      heroSub:
        "واز لە چاوەڕوانیی مووچەی دواکەوتوو بهێنە. لە ڕێگەی سیستەمی زیرەکی دەستکردمانەوە، یەکسەر ڤیدیۆکانی دووکانەکەت بکە بە عەرەبی عێراقی و ئەو گەشتیارانەی بە بەردەم دەرگاکەتدا تێدەپەڕن بکە بە کڕیاری ڕاستەقینە.",
      inputPlaceholder: "ژمارەی وەتسئەپ بنووسە (+964 7XX...)",
      ctaPrimary: "لە ١٠ چرکەدا وەتسئەپەکەم ببەستەوە",
      ctaSubtext: "⚡ تاقیکردنەوەی بێبەرامبەر • پێویست بە کارتی بانک ناکات",

      splitLeftTitle: "(دووکانەکەت لە ئێستادا)",
      splitLeftStatus: "سارد و بێ کڕیار",
      splitLeftItem1: "❌ چاوەڕوانی مووچەی حکومیی دواکەوتوو",
      splitLeftItem2: "❌ کەڵەکەبوونی زیاتر لە دەفتەرێک بەهای کەلوپەلی نەفرۆشراو",
      splitLeftItem3: "❌ گەشتیاری عەرەب بە بەردەمتدا تێدەپەڕێت و ناتبینێت",
      splitLeftMetric: "$0 داهات لە گەشتیار",

      splitRightTitle: "(دووکانەکەت بە Doblaj AI)",
      splitRightStatus: "کاش و فرۆشی بەردەوام",
      splitRightItem1: "✅ ڤیدیۆی سۆرانی یەکسەر دەبێتە عەرەبی عێراقی پاراو",
      splitRightItem2: "✅ گەشتیار لە تیکتۆک دەتبینێت و ڕاستەوخۆ دێتە دووکانەکەت",
      splitRightItem3: "✅ فرۆشی ڕۆژانە بە گەشتیارانی بەغدا و بەسرە",
      splitRightMetric: "+١,٥٠٠,٠٠٠ دینار تێکڕای قازانجی کۆتایی هەفتە",
      splitBottomNote: "(تێبینی: تەنها یەک فرۆش بە گەشتیارێکی عەرەب، تێچووی تەواوی مانگێکی ئەم سیستەمە دەردێنێتەوە. باقی ٢٩ ڕۆژەکەی تر ١٠٠٪ قازانجی ساغە بۆ خۆت).",

      painSectionTag: "زەنگی مەترسیی ناوچەیی",
      painHeadline: "کەلوپەلەکەت بێ کڕیار ماوەتەوە، لە کاتێکدا ڕکابەرەکانت پارەی گەشتیاران دەبەن.",
      painBody:
        "لە کاتێکدا تۆ لەسەر هەزاران دۆلار کەلوپەلی هاوینەی نەفرۆشراو دانیشتووی، ١٤ دووکانی تر لە سلێمانی و هەولێر زیرەکی دەستکرد بەکاردەهێنن و گەشتیارانی عەرەب ڕاستەوخۆ دەهێننە ناو پێشانگاکانیان.",
      mapTitle: "نەخشەی زیندووی دووکانە چالاکەکان لە سلێمانی و هەولێر",
      mapSubtitle: "خاڵە ڕووناکەکان ئەو دووکانانەن کە ئەم هەفتەیە ڤیدیۆیان دۆبلاژ کردووە",

      pricingAnchor: "کرێی وەرگێڕی مرۆیی بۆ دەنگی عەرەبی:",
      pricingAnchorOld: "$500 / مانگانە",
      pricingAnchorSave: "٩٦٪ پاشەکەوت بکە بە Doblaj AI",
      pricingTitle: "نرخی ڕزگارکردنی کاسبییەکەت",
      pricingSubtitle: "تەنها یەک فرۆش بە گەشتیارێکی عەرەب، تێچووی تەواوی ساڵێکی ئەم سیستەمە دەردێنێتەوە.",

      decoyTitle: "دەستپێکی سنووردار (داو)",
      decoyPrice: "$15",
      decoyPeriod: "/مانگ",
      decoyLimit: "تەنها یەک ڤیدیۆ",
      decoyItem1: "ڕیزبەندیی هێواشی کارکردن",
      decoyItem2: "کواڵێتی ئاسایی 720p",
      decoyItem3: "دەنگی سادە",
      decoyCta: "تەنها ١ ڤیدیۆ ($15)",

      targetBadge: "🔥 پڕداواکراوترین — هەلی زێڕینی دووکاندار",
      targetTitle: "پلانی گەشەی بێسنوور",
      targetPrice: "$20",
      targetPeriod: "/مانگ",
      targetLimit: "ڤیدیۆی بێسنوور (تا ١٥ خولەک)",
      targetItem1: "⚡ خێرایی لەپێشینەی دەستبەجێ",
      targetItem2: "✨ شێوەزاری عێراقیی پاراو و هەستی سروشتی",
      targetItem3: "🎥 کواڵێتی 4K Ultra-HD بۆ ئینستاگرام و تیکتۆک",
      targetItem4: "🗣️ پاراستنی میوزیک و دەنگی پشتەوەی ڤیدیۆکە",
      targetMicroCopy: "💡 کەمترە لە قازانجی فرۆشتنی تەنها یەک تیشێرت!",
      targetCta: "ئێستا دەست بە پلانی $20 بێسنوور بکە",

      anchorTitle: "ئاژانس و کۆمپانیا",
      anchorPrice: "$99",
      anchorPeriod: "/مانگ",
      anchorLimit: "١٢٠ خولەک بۆ فرە-لق",
      anchorItem1: "ڕاڕەوی خێرای VIP تایبەت",
      anchorItem2: "ناسینەوەی فرە-قسەکەر لە یەک کاتدا",
      anchorItem3: "کڵۆنکردنی دەنگی تایبەتی کارمەندانت",
      anchorItem4: "بەستنەوە بە API و پشتگیریی بەردەوام",
      anchorCta: "پلانی کۆمپانیا ($99)",

      paymentTrust: "🔒 پارەدان بە دڵنیایی لە ڕێگەی فاستپەی (FastPay)، FIB، زەین کاش، ڤیزا و ماستەرکارت.",

      faqTitle: "وەڵامی ئەو پرسیارانەی لە مێشکتدان",
      faqSubtitle: "بەر لەوەی دووکاندارەکەی تەنیشتت گەشتیارەکان بۆ لای خۆی ڕابکێشێت بیخوێنەرەوە.",

      faq1Q: "ناتوانم تەنها ژێرنووسی عەرەبیی بێبەرامبەر (نووسین) لەسەر ڤیدیۆکەم دابنێم؟",
      faq1A:
        "هیچ کەسێک لە ناو بازاڕی قەرەباڵغ یان لە کاتی سەیرکردنی خێرای تیکتۆک ناوەستێت بۆ خوێندنەوەی دەقی وردی ژێرنووس. گەشتیار کاتێک دەکڕێت کە گوێی لە دەنگێکی عەرەبی عێراقیی گەرم و ڕەسەن بێت کە بە شێوەزاری خۆی بەخێرهاتنی دەکات. ژێرنووس پشتگوێ دەخرێت، بەڵام دەنگی سروشتی لە چەند چرکەیەکدا کڕیار دەهێنێتە دووکانەکەت.",

      faq2Q: "من کاسبکارم و شارەزایی بەرزی کۆمپیوتەرم نییە، ئایا ئەمە ئاڵۆز نییە بۆ من؟",
      faq2A:
        "پێویست ناکات ئەندازیاری پرۆگرامسازی بیت—تۆ کاسبکارێکی زیرەکیت. ئەگەر بزانیت چۆن لە وەتسئەپ ڤیدیۆ دەنێریت یان لە ئینستاگرام ستۆری دادەنێیت، لە ١٠ چرکەدا دەتوانیت Doblaj بەکاربهێنیت. تەنها ڤیدیۆکەت باردەکەیت، زیرەکی دەستکرد بە عەرەبی عێراقی قسەی پێدەکات و تۆ بڵاوی دەکەیتەوە. تایبەت بۆ کاسبکارانی سەرقاڵ دروستکراوە.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • ئۆستن، تەکساس، ئەمریکا",
      navFeatures: "سوودەکان",
      navMap: "نەخشەی چالاک",
      navPricing: "نرخەکان",
      navFaq: "پرسیارەکان",
      navLogin: "داشبۆرد",
      navStart: "دەستپێکردن",
    },
    ar: {
      badge: "🚨 تنبيه لأصحاب المحلات والمعارض في السليمانية وأربيل",
      heroHeadlineStart: "السوق المحلي راكد وما بيه سيولة.",
      heroHeadlineHighlight: "السياح العرب د يصرفون مليارات الدنانير.",
      heroHeadlineEnd: "محلك ديحچي ويّا يا سوق؟",
      heroSub:
        "لتنتظر رواتب تتأخر. عن طريق نظام الذكاء الاصطناعي مالتنا، دبلج فيديوهات محلك للهجة العراقية بلحظات وحوّل السياح اللي يمرون من يم بابك إلى زبائن حقيقيين.",
      inputPlaceholder: "اكتب رقم الواتساب (+964 7XX...)",
      ctaPrimary: "اربط رقم الواتساب بـ ١٠ ثواني",
      ctaSubtext: "⚡ تجربة مجانية فورية • بدون الحاجة لبطاقة بنكية",

      splitLeftTitle: "(محلك بالوضع الحالي)",
      splitLeftStatus: "سوق بارد وهادئ",
      splitLeftItem1: "❌ انتظار رواتب الموظفين المتأخرة",
      splitLeftItem2: "❌ بضاعة مكدسة بالمحل بأكثر من دفتر (١٠,٠٠٠$)",
      splitLeftItem3: "❌ السائح العربي يمر من يم بابك وميشوفك أصلاً",
      splitLeftMetric: "$0 مبيعات من السياح",

      splitRightTitle: "(محلك مع Doblaj AI)",
      splitRightStatus: "كاش وسياح يومياً",
      splitRightItem1: "✅ فيديوهاتك الكردية تدبلج فوراً للهجة عراقية بغدادية",
      splitRightItem2: "✅ السائح يشوفك بالتيك توك ويجيك مباشرة للمحل",
      splitRightItem3: "✅ مبيعات يومية لسياح بغداد والبصرة",
      splitRightMetric: "+١,٥٠٠,٠٠٠ دينار تێکڕای أرباح الويكند",
      splitBottomNote: "(ملاحظة: بيعة واحدة لسائح عربي تطلع تكلفة اشتراك شهر كامل من هذا النظام. باقي الـ ٢٩ يوم أرباح صافية ١٠٠٪ لجيبك).",

      painSectionTag: "جرس إنذار محلي",
      painHeadline: "بينما بضاعتك نايمة بالمحل، منافسينك د ياخذون فلوس السياح.",
      painBody:
        "بينما أنت كاعد على بضاعة صيفية بآلاف الدولارات ما مباعة، اكو ١٤ محل ومعرض بالسليمانية وأربيل ديستعملون نظامنا ود يجيبون السياح العرب لمحلاتهم يومياً.",
      mapTitle: "خارطة حية للمحلات النشطة في السليمانية وأربيل",
      mapSubtitle: "النقاط المضيئة تمثل محلات دبلجت فيديوهات إعلانية هذا الأسبوع",

      pricingAnchor: "تكلفة توظيف مترجم ومعلق صوتي عربي شهرياً:",
      pricingAnchorOld: "$500 / شهرياً",
      pricingAnchorSave: "وفّر ٩٦٪ فوراً مع Doblaj AI",
      pricingTitle: "أسعار خطة النجاة وزيادة المبيعات",
      pricingSubtitle: "بيعة وحدة لسائح عربي تطلعلك تكلفة اشتراك سنة كاملة من هذا البرنامج.",

      decoyTitle: "الباقة التجريبية (فخ)",
      decoyPrice: "$15",
      decoyPeriod: "/شهر",
      decoyLimit: "فيديو واحد فقط",
      decoyItem1: "معالجة بطيئة",
      decoyItem2: "دقة عادية 720p",
      decoyItem3: "صوت آلي بسيط",
      decoyCta: "فيديو واحد فقط ($15)",

      targetBadge: "🔥 الأكثر طلباً — خطة التوسع والنمو",
      targetTitle: "باقة المحلات الذكية",
      targetPrice: "$20",
      targetPeriod: "/شهر",
      targetLimit: "فيديوهات غير محدودة (حتى ١٥ دقيقة)",
      targetItem1: "⚡ أولوية قصوى ومعالجة فورية",
      targetItem2: "✨ لهجة عراقية بغدادية أصلية بمشاعر حقيقية",
      targetItem3: "🎥 تصدير بدقة 4K Ultra-HD للإنستغرام والتيك توك",
      targetItem4: "🗣️ عزل صوت الغرفة والموسيقى التصويرية تلقائياً",
      targetMicroCopy: "💡 تكلفتها أقل من ربح بيع تيشرت واحد بمحلك!",
      targetCta: "اشترك الآن بـ $20 للفيديوهات غير المحدودة",

      anchorTitle: "باقة الوكالات والشركات",
      anchorPrice: "$99",
      anchorPeriod: "/شهر",
      anchorLimit: "١٢٠ دقيقة للفروع المتعددة",
      anchorItem1: "معالجة VIP بأعلى سرعة سيرفرات",
      anchorItem2: "تمييز تلقائي لعدة متحدثين بالفيديو",
      anchorItem3: "استنساخ صوت كادرك الخاص",
      anchorItem4: "ربط برمجيات API ودعم فني مخصص",
      anchorCta: "باقة الوكالات ($99)",

      paymentTrust: "🔒 دفع آمن وسهل عبر فاست باي (FastPay)، زين كاش، FIB، فيزا وماستركارد.",

      faqTitle: "إجابات على مخاوفك وترددك",
      faqSubtitle: "اقرأها قبل ما المحل اللي بصفك يسحب كل سياح شارعكم.",

      faq1Q: "ليش ما أحط ترجمة كتابية (Subtitles) مجانية على الفيديو وخلاص؟",
      faq1A:
        "محد يفتر بالسوق المزدحم أو يقلب بالتيك توك ويكعد يقرا كتابة ناعمة. السائح العراقي يشتري من يسمع صوت عراقي حقيقي ولهجة بغدادية مألوفة ترحب بيه مباشرة. الكتابة الناس تتخطاها بـ ٠.٥ ثانية، بس الصوت العراقي الطبيعي يسحب الزبون لمحلك بثواني.",

      faq2Q: "أني صاحب محل مو مبرمج، هل البرنامج صعب ومعقد عليّ؟",
      faq2A:
        "ما تحتاج تكون خبير تقني—أنت صاحب عمل ذكي. إذا تعرف تدز فيديو بالواتساب أو تنشر ستوري بالانستغرام، تكدر تستعمل Doblaj بـ ١٠ ثواني. ترفع الفيديو الكردي، الذكاء الاصطناعي يدبلجه باللهجة العراقية، وتنشره. مصمم خصيصاً لأصحاب المحلات المشغولين اللي يريدون مبيعات بدون دوخة رأس.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • أوستن، تكساس، الولايات المتحدة",
      navFeatures: "المقارنة",
      navMap: "الخارطة الحية",
      navPricing: "الأسعار",
      navFaq: "الأسئلة الشائعة",
      navLogin: "لوحة التحكم",
      navStart: "ابدأ الآن",
    },
  }[lang];

  const handleWhatsAppSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanNumber = whatsAppNumber.replace(/[^0-9]/g, "");
    if (isSignedIn) {
      navigate("/dubbing");
    } else {
      navigate(`/sign-up?redirect_url=${encodeURIComponent('/dubbing')}&phone=${cleanNumber}`);
    }
  };

  return (
    <div
      dir={isRTL ? "rtl" : "ltr"}
      className="min-h-screen bg-[#070709] text-[#cfcfd3] font-sans antialiased selection:bg-[#22c55e]/20 selection:text-[#22c55e]"
    >
      {/* Sticky Header */}
      <nav className="fixed top-0 w-full z-50 bg-[#070709]/90 backdrop-blur-xl border-b border-white/[0.08] shadow-2xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-10 flex justify-between items-center h-20">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-[#22c55e] to-[#047857] p-0.5 flex items-center justify-center shadow-[0_0_20px_rgba(34,197,94,0.3)] group-hover:scale-105 transition-transform">
              <div className="w-full h-full bg-[#070709] rounded-[10px] flex items-center justify-center">
                <span className="text-[#22c55e] font-black text-xl tracking-tighter">DB</span>
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-2xl font-extrabold text-[#fafafa] tracking-tight group-hover:text-[#22c55e] transition-colors leading-none">
                Doblaj
              </span>
              <span className="text-[10px] font-mono uppercase tracking-widest text-[#22c55e] font-bold mt-1">
                Retail Growth AI
              </span>
            </div>
          </Link>

          <div className="hidden md:flex items-center gap-8 text-sm font-semibold">
            <a href="#contrast-hero" className="text-[#cfcfd3] hover:text-[#22c55e] transition-colors">
              {t.navFeatures}
            </a>
            <a href="#territorial-map" className="text-[#cfcfd3] hover:text-[#22c55e] transition-colors">
              {t.navMap}
            </a>
            <a href="#pricing" className="text-[#cfcfd3] hover:text-[#22c55e] transition-colors">
              {t.navPricing}
            </a>
            <a href="#faq" className="text-[#cfcfd3] hover:text-[#22c55e] transition-colors">
              {t.navFaq}
            </a>
          </div>

          <div className="hidden md:flex items-center gap-4">
            <div className="flex items-center bg-[#121217] border border-white/[0.08] rounded-xl p-1 text-xs">
              <button
                onClick={() => setLang("ckb")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "ckb" ? "bg-[#22c55e] text-[#070709] shadow-md" : "text-[#cfcfd3] hover:text-white"
                }`}
              >
                سۆرانی
              </button>
              <button
                onClick={() => setLang("ar")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "ar" ? "bg-[#22c55e] text-[#070709] shadow-md" : "text-[#cfcfd3] hover:text-white"
                }`}
              >
                عربي
              </button>
              <button
                onClick={() => setLang("en")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "en" ? "bg-[#22c55e] text-[#070709] shadow-md" : "text-[#cfcfd3] hover:text-white"
                }`}
              >
                EN
              </button>
            </div>

            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="inline-flex items-center justify-center px-6 py-3 rounded-xl bg-[#22c55e] hover:bg-[#16a34a] text-[#070709] text-sm font-extrabold shadow-[0_0_25px_rgba(34,197,94,0.35)] transition-all transform hover:scale-[1.02] active:scale-[0.98]"
            >
              {isSignedIn ? t.navLogin : t.navStart}
            </Link>
          </div>

          <button
            onClick={() => setMobileMenu(!mobileMenu)}
            aria-label="Toggle menu"
            className="md:hidden text-[#cfcfd3] hover:text-[#22c55e] p-2"
          >
            <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>

        {mobileMenu && (
          <div className="md:hidden bg-[#0a0a0f] border-b border-white/[0.1] px-6 py-6 space-y-4 shadow-2xl">
            <div className="flex justify-center gap-2 mb-4 bg-[#121217] p-1.5 rounded-xl border border-white/[0.08]">
              <button
                onClick={() => setLang("ckb")}
                className={`flex-1 py-2 rounded-lg font-bold text-sm ${
                  lang === "ckb" ? "bg-[#22c55e] text-[#070709]" : "text-[#cfcfd3]"
                }`}
              >
                سۆرانی
              </button>
              <button
                onClick={() => setLang("ar")}
                className={`flex-1 py-2 rounded-lg font-bold text-sm ${
                  lang === "ar" ? "bg-[#22c55e] text-[#070709]" : "text-[#cfcfd3]"
                }`}
              >
                عربي
              </button>
              <button
                onClick={() => setLang("en")}
                className={`flex-1 py-2 rounded-lg font-bold text-sm ${
                  lang === "en" ? "bg-[#22c55e] text-[#070709]" : "text-[#cfcfd3]"
                }`}
              >
                EN
              </button>
            </div>
            <a href="#contrast-hero" className="block text-base font-semibold text-[#cfcfd3]">
              {t.navFeatures}
            </a>
            <a href="#territorial-map" className="block text-base font-semibold text-[#cfcfd3]">
              {t.navMap}
            </a>
            <a href="#pricing" className="block text-base font-semibold text-[#cfcfd3]">
              {t.navPricing}
            </a>
            <a href="#faq" className="block text-base font-semibold text-[#cfcfd3]">
              {t.navFaq}
            </a>
            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="block w-full text-center px-6 py-3.5 rounded-xl bg-[#22c55e] text-[#070709] font-extrabold text-sm shadow-[0_0_20px_rgba(34,197,94,0.3)]"
            >
              {isSignedIn ? t.navLogin : t.navStart}
            </Link>
          </div>
        )}
      </nav>

      {/* SECTION 1: THE HERO SECTION (Extreme Contrast & Context Change) */}
      <section id="contrast-hero" className="relative pt-32 pb-20 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto overflow-hidden">
        {/* Urgent Warning Badge */}
        <div className="flex justify-center mb-8">
          <div className="inline-flex items-center gap-2.5 px-4 py-2 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs sm:text-sm font-bold tracking-wide animate-pulse">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.8)]"></span>
            {t.badge}
          </div>
        </div>

        {/* Shock Headline */}
        <div className="text-center max-w-4xl mx-auto mb-10 space-y-4">
          <h1 className="text-3xl sm:text-5xl lg:text-6xl font-black text-[#fafafa] tracking-tight leading-[1.2]">
            <span className="text-rose-400 block mb-2">{t.heroHeadlineStart}</span>
            <span className="text-[#22c55e] block mb-2 drop-shadow-[0_0_25px_rgba(34,197,94,0.25)]">
              {t.heroHeadlineHighlight}
            </span>
            <span className="text-white">{t.heroHeadlineEnd}</span>
          </h1>

          <p className="text-lg sm:text-xl text-[#cfcfd3] max-w-3xl mx-auto font-medium leading-relaxed pt-2">
            {t.heroSub}
          </p>
        </div>

        {/* Ultra-Fast Action Bar (Minimizing Friction) */}
        <div className="max-w-2xl mx-auto mb-16">
          <form
            onSubmit={handleWhatsAppSubmit}
            className="bg-[#121217] p-2.5 sm:p-3 rounded-2xl border-2 border-[#22c55e]/40 shadow-[0_0_40px_rgba(34,197,94,0.2)] flex flex-col sm:flex-row gap-3"
          >
            <input
              type="text"
              value={whatsAppNumber}
              onChange={(e) => setWhatsAppNumber(e.target.value)}
              placeholder={t.inputPlaceholder}
              className="flex-1 bg-[#09090d] border border-white/[0.1] rounded-xl px-5 py-4 text-[#fafafa] placeholder:text-[#6b6b78] font-mono text-base focus:outline-none focus:border-[#22c55e] transition-colors"
            />
            <button
              type="submit"
              className="px-8 py-4 rounded-xl bg-[#22c55e] hover:bg-[#16a34a] text-[#070709] font-black text-base shadow-[0_0_25px_rgba(34,197,94,0.5)] transition-all transform hover:scale-[1.02] active:scale-[0.98] animate-pulse"
            >
              {t.ctaPrimary}
            </button>
          </form>
          <div className="text-center mt-3 text-xs font-semibold text-[#8e8e9c]">
            {t.ctaSubtext}
          </div>
        </div>

        {/* Extreme Split Screen Visual Comparison (Pain Frame vs Escape Route) */}
        <div className="grid lg:grid-cols-2 gap-8 items-stretch">
          {/* Left: The Dark / Pain Store */}
          <div className="bg-[#0f0f14] border border-rose-900/30 rounded-3xl p-8 sm:p-10 flex flex-col justify-between relative overflow-hidden shadow-2xl group hover:border-rose-700/50 transition-colors">
            <div className="absolute top-0 right-0 left-0 h-1.5 bg-rose-600"></div>
            <div>
              <div className="flex justify-between items-center mb-4">
                <span className="px-3.5 py-1.5 rounded-full text-xs sm:text-sm font-black uppercase tracking-wider bg-rose-500/15 text-rose-400 border border-rose-500/30 flex items-center gap-1.5">
                  <span>{t.splitLeftStatus}</span>
                  <span>🥀</span>
                </span>
              </div>
              <h3 className="text-lg sm:text-xl font-bold text-[#a1a1aa] mb-6">
                {t.splitLeftTitle}
              </h3>
              <ul className="space-y-4 text-sm sm:text-base text-[#d4d4d8] mb-8 font-medium">
                <li className="flex items-start gap-2">
                  <span>{t.splitLeftItem1}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span>{t.splitLeftItem2}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span>{t.splitLeftItem3}</span>
                </li>
              </ul>
            </div>
            <div className="p-4 rounded-2xl bg-black/60 border border-rose-900/40 text-center">
              <div className="text-2xl sm:text-3xl font-black text-rose-500 font-mono">
                {t.splitLeftMetric}
              </div>
            </div>
          </div>

          {/* Right: The Wealth / Escape Store */}
          <div className="bg-gradient-to-b from-[#121b15] to-[#0d1410] border-2 border-[#22c55e] rounded-3xl p-8 sm:p-10 flex flex-col justify-between relative overflow-hidden shadow-[0_0_50px_rgba(34,197,94,0.15)] group hover:border-[#22c55e] transition-all">
            <div className="absolute top-0 right-0 left-0 h-2 bg-[#22c55e] shadow-[0_0_15px_rgba(34,197,94,0.8)]"></div>
            <div>
              <div className="flex justify-between items-center mb-4">
                <span className="px-3.5 py-1.5 rounded-full text-xs sm:text-sm font-black uppercase tracking-wider bg-[#22c55e]/20 text-[#22c55e] border border-[#22c55e]/40 shadow-[0_0_10px_rgba(34,197,94,0.3)] flex items-center gap-1.5">
                  <span>{t.splitRightStatus}</span>
                  <span>💰</span>
                </span>
              </div>
              <h3 className="text-lg sm:text-xl font-bold text-[#86efac] mb-6">
                {t.splitRightTitle}
              </h3>
              <ul className="space-y-4 text-sm sm:text-base text-[#fafafa] mb-8 font-medium">
                <li className="flex items-start gap-2">
                  <span>{t.splitRightItem1}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span>{t.splitRightItem2}</span>
                </li>
                <li className="flex items-start gap-2">
                  <span>{t.splitRightItem3}</span>
                </li>
              </ul>
            </div>
            <div className="p-4 rounded-2xl bg-[#070709]/90 border border-[#22c55e]/50 text-center shadow-lg">
              <div className="text-2xl sm:text-3xl font-black text-[#22c55e] font-mono drop-shadow-[0_0_15px_rgba(34,197,94,0.4)]">
                {t.splitRightMetric}
              </div>
            </div>
          </div>
        </div>

        {/* Psychological ROI Note */}
        <div className="mt-8 text-center max-w-3xl mx-auto">
          <p className="text-xs sm:text-sm md:text-base font-bold text-[#22c55e] bg-[#22c55e]/10 border border-[#22c55e]/30 rounded-2xl py-3.5 px-6 shadow-[0_0_25px_rgba(34,197,94,0.15)] leading-relaxed">
            {t.splitBottomNote}
          </p>
        </div>
      </section>

      {/* SECTION 2: THE AGITATION SECTION & TERRITORIAL PANIC */}
      <section id="territorial-map" className="py-24 px-4 sm:px-6 lg:px-10 bg-[#0d0d12] border-y border-white/[0.08]">
        <div className="max-w-7xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
            <div className="inline-block px-3.5 py-1 rounded-full text-xs font-black uppercase tracking-widest bg-amber-500/15 text-amber-400 border border-amber-500/30">
              {t.painSectionTag}
            </div>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-black text-[#fafafa] tracking-tight">
              {t.painHeadline}
            </h2>
            <p className="text-base sm:text-lg text-[#a1a1aa] font-medium leading-relaxed">
              {t.painBody}
            </p>
          </div>

          {/* Stylized Dark Territorial Radar Map */}
          <div className="bg-[#121219] rounded-3xl p-6 sm:p-10 border border-white/[0.1] shadow-2xl relative overflow-hidden">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8 pb-6 border-b border-white/[0.08]">
              <div>
                <h3 className="text-xl sm:text-2xl font-bold text-[#fafafa]">
                  {t.mapTitle}
                </h3>
                <p className="text-xs sm:text-sm text-[#8e8e9c] mt-1">
                  {t.mapSubtitle}
                </p>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#070709] border border-[#22c55e]/30">
                <span className="w-2.5 h-2.5 rounded-full bg-[#22c55e] animate-ping"></span>
                <span className="text-xs font-mono font-bold text-[#22c55e]">14 Stores Live Right Now</span>
              </div>
            </div>

            {/* Radar Grid Graphic */}
            <div className="relative w-full aspect-[16/9] min-h-[360px] bg-[#070709] rounded-2xl border border-white/[0.06] overflow-hidden p-6 flex items-center justify-center">
              {/* Radar Grid Lines */}
              <div className="absolute inset-0 bg-[radial-gradient(#22c55e_1px,transparent_1px)] [background-size:24px_24px] opacity-15"></div>
              <div className="absolute w-96 h-96 rounded-full border border-[#22c55e]/15 animate-ping opacity-20 pointer-events-none"></div>

              {/* Sulaymaniyah & Erbil Visual Corridor */}
              <div className="relative w-full h-full">
                {/* Hotspot 1: Salim Street */}
                <div className="absolute top-[30%] left-[25%] -translate-x-1/2 -translate-y-1/2 group cursor-pointer">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-full bg-[#22c55e]/40 animate-ping"></span>
                    <span className="relative w-4 h-4 rounded-full bg-[#22c55e] border-2 border-white shadow-[0_0_12px_#22c55e]"></span>
                  </div>
                  <div className="mt-2 bg-[#121217]/95 border border-[#22c55e]/40 px-3 py-1.5 rounded-xl text-center shadow-xl backdrop-blur-md">
                    <div className="text-[11px] font-bold text-[#fafafa] whitespace-nowrap">📍 Salim Street (شەقامی سەلیم)</div>
                    <div className="text-[9px] font-mono text-[#22c55e] font-semibold">5 Shops Active • 28 Dubs</div>
                  </div>
                </div>

                {/* Hotspot 2: Mawlawi Bazaar */}
                <div className="absolute top-[65%] left-[38%] -translate-x-1/2 -translate-y-1/2 group cursor-pointer">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-full bg-[#22c55e]/40 animate-ping"></span>
                    <span className="relative w-4 h-4 rounded-full bg-[#22c55e] border-2 border-white shadow-[0_0_12px_#22c55e]"></span>
                  </div>
                  <div className="mt-2 bg-[#121217]/95 border border-[#22c55e]/40 px-3 py-1.5 rounded-xl text-center shadow-xl backdrop-blur-md">
                    <div className="text-[11px] font-bold text-[#fafafa] whitespace-nowrap">📍 Mawlawi Street (مەولەوی)</div>
                    <div className="text-[9px] font-mono text-[#22c55e] font-semibold">4 Showrooms Active • 41 Dubs</div>
                  </div>
                </div>

                {/* Hotspot 3: Saholaka */}
                <div className="absolute top-[40%] left-[55%] -translate-x-1/2 -translate-y-1/2 group cursor-pointer">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-full bg-[#22c55e]/40 animate-ping"></span>
                    <span className="relative w-4 h-4 rounded-full bg-[#22c55e] border-2 border-white shadow-[0_0_12px_#22c55e]"></span>
                  </div>
                  <div className="mt-2 bg-[#121217]/95 border border-[#22c55e]/40 px-3 py-1.5 rounded-xl text-center shadow-xl backdrop-blur-md">
                    <div className="text-[11px] font-bold text-[#fafafa] whitespace-nowrap">📍 Saholaka (سەهۆڵەکە)</div>
                    <div className="text-[9px] font-mono text-[#22c55e] font-semibold">3 Stores Active • 19 Dubs</div>
                  </div>
                </div>

                {/* Hotspot 4: Erbil Empire & Family Mall */}
                <div className="absolute top-[35%] left-[78%] -translate-x-1/2 -translate-y-1/2 group cursor-pointer">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-full bg-[#22c55e]/40 animate-ping"></span>
                    <span className="relative w-4 h-4 rounded-full bg-[#22c55e] border-2 border-white shadow-[0_0_12px_#22c55e]"></span>
                  </div>
                  <div className="mt-2 bg-[#121217]/95 border border-[#22c55e]/40 px-3 py-1.5 rounded-xl text-center shadow-xl backdrop-blur-md">
                    <div className="text-[11px] font-bold text-[#fafafa] whitespace-nowrap">📍 Erbil / Empire (هەولێر)</div>
                    <div className="text-[9px] font-mono text-[#22c55e] font-semibold">2 Boutiques Active • 33 Dubs</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 3: THE PRICING GUILLOTINE (Decoy Effect & Price Anchoring) */}
      <section id="pricing" className="py-24 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto">
        <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
          {/* Top Red Anchor Crossed Out */}
          <div className="inline-flex flex-col sm:flex-row items-center gap-2 p-3 sm:px-6 sm:py-2.5 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-sm font-bold">
            <span className="text-[#a1a1aa]">{t.pricingAnchor}</span>
            <span className="line-through text-rose-500 font-extrabold text-base">{t.pricingAnchorOld}</span>
            <span className="text-[#22c55e] bg-[#22c55e]/15 px-2.5 py-0.5 rounded-full text-xs font-black">
              {t.pricingAnchorSave}
            </span>
          </div>

          <h2 className="text-3xl sm:text-5xl font-black text-[#fafafa] tracking-tight">
            {t.pricingTitle}
          </h2>
          <p className="text-base sm:text-lg text-[#22c55e] font-bold">
            {t.pricingSubtitle}
          </p>
        </div>

        {/* The 3 Manipulated Tiers */}
        <div className="grid lg:grid-cols-3 gap-8 items-center max-w-6xl mx-auto">
          {/* Tier 1: The $15 Decoy (Visually Weak, Flat Gray, Small) */}
          <div className="bg-[#111116] rounded-3xl p-6 sm:p-8 border border-white/[0.06] flex flex-col justify-between opacity-80 hover:opacity-100 transition-opacity">
            <div>
              <div className="text-xs uppercase font-mono text-[#71717a] font-bold mb-2">
                {t.decoyTitle}
              </div>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-4xl font-extrabold text-[#a1a1aa]">{t.decoyPrice}</span>
                <span className="text-xs text-[#71717a]">{t.decoyPeriod}</span>
              </div>
              <div className="text-xs font-bold text-rose-400/80 mb-6 bg-rose-500/10 px-2.5 py-1 rounded-lg inline-block">
                ⚠️ {t.decoyLimit}
              </div>
              <ul className="space-y-3 text-xs text-[#8e8e9c] mb-8">
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem1}</li>
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem2}</li>
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem3}</li>
              </ul>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=starter" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=starter')}`}
              className="w-full py-3 rounded-xl border border-white/[0.1] text-center text-xs font-bold text-[#a1a1aa] hover:bg-white/[0.04] transition-colors block"
            >
              {t.decoyCta}
            </Link>
          </div>

          {/* Tier 2: The $20 Target (15% Larger, Floating Drop Shadow, Neon Border, Breathing Button) */}
          <div className="bg-gradient-to-b from-[#142319] to-[#0c1610] rounded-3xl p-8 sm:p-10 border-2 border-[#22c55e] flex flex-col justify-between relative shadow-[0_0_60px_rgba(34,197,94,0.25)] transform lg:-translate-y-4">
            <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1.5 bg-[#22c55e] text-[#070709] text-xs font-black uppercase rounded-full shadow-[0_0_15px_rgba(34,197,94,0.8)] whitespace-nowrap">
              {t.targetBadge}
            </div>
            <div>
              <div className="text-xs uppercase font-mono text-[#22c55e] font-black tracking-wider mb-2">
                {t.targetTitle}
              </div>
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-6xl font-black text-[#fafafa] tracking-tight">{t.targetPrice}</span>
                <span className="text-sm font-bold text-[#a1a1aa]">{t.targetPeriod}</span>
              </div>
              <div className="text-sm font-black text-[#22c55e] mb-6 bg-[#22c55e]/15 px-3 py-1.5 rounded-xl inline-block border border-[#22c55e]/30">
                ✨ {t.targetLimit}
              </div>
              <ul className="space-y-3.5 text-sm font-semibold text-[#fafafa] mb-6">
                <li className="flex items-center gap-2.5"><span className="text-[#22c55e] font-black">✓</span> {t.targetItem1}</li>
                <li className="flex items-center gap-2.5"><span className="text-[#22c55e] font-black">✓</span> {t.targetItem2}</li>
                <li className="flex items-center gap-2.5"><span className="text-[#22c55e] font-black">✓</span> {t.targetItem3}</li>
                <li className="flex items-center gap-2.5"><span className="text-[#22c55e] font-black">✓</span> {t.targetItem4}</li>
              </ul>
              <div className="p-3 rounded-xl bg-black/40 border border-[#22c55e]/30 text-xs font-bold text-[#22c55e] text-center mb-6">
                {t.targetMicroCopy}
              </div>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=pro" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=pro')}`}
              className="w-full py-4 rounded-xl bg-[#22c55e] hover:bg-[#16a34a] text-[#070709] text-center text-base font-black shadow-[0_0_30px_rgba(34,197,94,0.6)] transition-all transform hover:scale-[1.03] active:scale-[0.98] animate-pulse block"
            >
              {t.targetCta}
            </Link>
          </div>

          {/* Tier 3: The $99 Anchor (Heavy, Dark Imposing Agency Tier) */}
          <div className="bg-[#0e0e13] rounded-3xl p-6 sm:p-8 border border-white/[0.08] flex flex-col justify-between shadow-xl">
            <div>
              <div className="text-xs uppercase font-mono text-[#a1a1aa] font-bold mb-2">
                {t.anchorTitle}
              </div>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-4xl font-extrabold text-[#fafafa]">{t.anchorPrice}</span>
                <span className="text-xs text-[#71717a]">{t.anchorPeriod}</span>
              </div>
              <div className="text-xs font-bold text-[#a1a1aa] mb-6 bg-white/[0.05] px-2.5 py-1 rounded-lg inline-block">
                🏢 {t.anchorLimit}
              </div>
              <ul className="space-y-3 text-xs text-[#cfcfd3] mb-8 font-medium">
                <li className="flex items-center gap-2"><span className="text-[#22c55e]">✓</span> {t.anchorItem1}</li>
                <li className="flex items-center gap-2"><span className="text-[#22c55e]">✓</span> {t.anchorItem2}</li>
                <li className="flex items-center gap-2"><span className="text-[#22c55e]">✓</span> {t.anchorItem3}</li>
                <li className="flex items-center gap-2"><span className="text-[#22c55e]">✓</span> {t.anchorItem4}</li>
              </ul>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=creator" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=creator')}`}
              className="w-full py-3.5 rounded-xl border border-white/[0.15] text-center text-xs font-bold text-[#fafafa] hover:bg-white/[0.06] transition-colors block"
            >
              {t.anchorCta}
            </Link>
          </div>
        </div>

        {/* Frictionless Payment Trust Strip */}
        <div className="text-center mt-12 text-xs sm:text-sm font-semibold text-[#8e8e9c]">
          {t.paymentTrust}
        </div>
      </section>

      {/* SECTION 4: THE MANDATORY WEAPONIZED FAQs */}
      <section id="faq" className="py-24 px-4 sm:px-6 lg:px-10 bg-[#0a0a0f] border-t border-white/[0.08]">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16 space-y-4">
            <div className="inline-block px-3.5 py-1 rounded-full text-xs font-black uppercase tracking-widest bg-[#22c55e]/15 text-[#22c55e] border border-[#22c55e]/30">
              {t.navFaq}
            </div>
            <h2 className="text-3xl sm:text-5xl font-black text-[#fafafa] tracking-tight">
              {t.faqTitle}
            </h2>
            <p className="text-base sm:text-lg text-[#a1a1aa] font-medium">
              {t.faqSubtitle}
            </p>
          </div>

          <div className="space-y-6">
            {/* FAQ 1: Destroying the Subtitle Objection */}
            <div className="bg-[#121218] rounded-2xl p-6 sm:p-8 border border-white/[0.08] shadow-lg hover:border-[#22c55e]/40 transition-colors">
              <h3 className="text-lg sm:text-xl font-extrabold text-[#fafafa] mb-3 flex items-start gap-3">
                <span className="text-[#22c55e] font-black">Q:</span>
                <span>{t.faq1Q}</span>
              </h3>
              <p className="text-sm sm:text-base text-[#cfcfd3] leading-relaxed font-medium pl-6 sm:pl-7 border-l-2 border-[#22c55e]/40">
                {t.faq1A}
              </p>
            </div>

            {/* FAQ 2: Destroying the Non-Tech Shopkeeper Objection */}
            <div className="bg-[#121218] rounded-2xl p-6 sm:p-8 border border-white/[0.08] shadow-lg hover:border-[#22c55e]/40 transition-colors">
              <h3 className="text-lg sm:text-xl font-extrabold text-[#fafafa] mb-3 flex items-start gap-3">
                <span className="text-[#22c55e] font-black">Q:</span>
                <span>{t.faq2Q}</span>
              </h3>
              <p className="text-sm sm:text-base text-[#cfcfd3] leading-relaxed font-medium pl-6 sm:pl-7 border-l-2 border-[#22c55e]/40">
                {t.faq2A}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Dynamic Floating Social Proof Toast (Bottom Corner) */}
      <div
        className={`fixed bottom-6 ${
          isRTL ? "left-6" : "right-6"
        } z-40 max-w-sm w-full transition-all duration-500 transform ${
          showToast ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none"
        }`}
      >
        <div className="bg-[#12121a]/95 border-2 border-[#22c55e]/60 rounded-2xl p-4 shadow-[0_10px_35px_rgba(0,0,0,0.8)] backdrop-blur-xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#22c55e]/20 border border-[#22c55e]/40 flex items-center justify-center text-lg flex-shrink-0">
            ⚡
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-bold text-[#fafafa] leading-snug">
              {liveNotifications[toastIndex]?.text}
            </p>
            <span className="text-[10px] font-mono text-[#22c55e] font-bold">
              {liveNotifications[toastIndex]?.time}
            </span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="bg-[#050508] border-t border-white/[0.06] w-full py-16 px-4 sm:px-6 lg:px-10">
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-4 gap-12">
          <div className="col-span-1 md:col-span-2 space-y-4 pr-8">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#22c55e] to-[#047857] p-0.5 flex items-center justify-center shadow-lg">
                <div className="w-full h-full bg-[#070709] rounded-[8px] flex items-center justify-center">
                  <span className="text-[#22c55e] font-bold text-sm">DB</span>
                </div>
              </div>
              <span className="text-xl font-black text-[#fafafa]">Doblaj</span>
            </div>
            <p className="text-sm text-[#8e8e9c] max-w-sm leading-relaxed font-medium">
              Transforming Kurdish retail videos into Iraqi Arabic tourist magnets with state-of-the-art AI.
            </p>
            <div className="pt-2 text-xs text-[#71717a]">
              <p className="font-bold text-white">{t.footerLegal}</p>
            </div>
            <p className="text-xs text-[#52525b] pt-2">© 2026 FIXDAI LLC d/b/a Doblaj. All rights reserved.</p>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Product</h4>
            <ul className="space-y-3 text-sm font-medium">
              <li>
                <a href="#pricing" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">{t.navPricing}</a>
              </li>
              <li>
                <a href="#territorial-map" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">{t.navMap}</a>
              </li>
              <li>
                <a href="#faq" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">{t.navFaq}</a>
              </li>
            </ul>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Legal & Trust</h4>
            <ul className="space-y-3 text-sm font-medium">
              <li>
                <Link to="/privacy" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">Privacy Policy</Link>
              </li>
              <li>
                <Link to="/terms" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">Terms of Service</Link>
              </li>
              <li>
                <Link to="/refund-policy" className="text-[#8e8e9c] hover:text-[#22c55e] transition-colors">Refund Policy</Link>
              </li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  );
}
