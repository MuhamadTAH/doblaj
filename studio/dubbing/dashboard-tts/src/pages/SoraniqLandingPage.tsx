import React, { useState, useEffect, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@clerk/clerk-react";
import { motion, AnimatePresence } from "framer-motion";

export default function SoraniqLandingPage() {
  const { isSignedIn } = useAuth();
  const navigate = useNavigate();
  const [lang, setLang] = useState<"ckb" | "ar" | "en">("ckb");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [isAnnual, setIsAnnual] = useState(false);
  
  // Audio demo player state
  const [activeAudioTab, setActiveAudioTab] = useState<"kurdish" | "iraqi">("iraqi");
  const [isPlayingAudio, setIsPlayingAudio] = useState(true);
  const [audioProgress, setAudioProgress] = useState(42);

  // ROI Calculator state (IQD Direct Architecture)
  const [avgProfitPerCustomer, setAvgProfitPerCustomer] = useState(10000); // 10,000 IQD default
  const [touristCustomers, setTouristCustomers] = useState(10); // 10 customers default

  // FAQ open state
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  // Simulated audio progress timer
  useEffect(() => {
    if (!isPlayingAudio) return;
    const interval = setInterval(() => {
      setAudioProgress((prev) => (prev >= 100 ? 0 : prev + 1.5));
    }, 150);
    return () => clearInterval(interval);
  }, [isPlayingAudio]);

  const isRTL = lang === "ckb" || lang === "ar";

  // Direct intuitive calculation: 1 customer = 10,000, 2 = 20,000, 10 = 100,000
  const totalCalculatedProfitIQD = touristCustomers * avgProfitPerCustomer;

  const t = {
    ckb: {
      badge: "🚨 ئاگاداری: بۆ خاوەن دووکان و پێشانگاکانی سلێمانی و هەولێر",
      heroHeadlineStart: "بازاڕی خۆماڵی سستە و بێ پارەیە.",
      heroHeadlineHighlight: "گەشتیارە عەرەبەکان ملیاران دینار خەرج دەکەن.",
      heroHeadlineEnd: "دووکانەکەت قسە بۆ کام بازاڕ دەکات؟",
      heroSub:
        "واز لە چاوەڕوانیی مووچەی دواکەوتوو بهێنە. لە ڕێگەی سیستەمی زیرەکی دەستکردمانەوە، یەکسەر ڤیدیۆکانی دووکانەکەت بکە بە عەرەبی عێراقی و ئەو گەشتیارانەی بە بەردەم دەرگاکەتدا تێدەپەڕن بکە بە کڕیاری ڕاستەقینە.",
      ctaHeroMassive: "یەکسەر دەست پێبکە (لینککردنی وەتسئەپ لە ١٠ چرکەدا)",
      inputPlaceholder: "ژمارەی وەتسئەپ بنووسە (+964 7XX...)",
      ctaPrimary: "لە ١٠ چرکەدا وەتسئەپەکەم ببەستەوە",
      ctaSubtext: "⚡ تاقیکردنەوەی دەستبەجێ بە خۆڕایی • پێویست بە کارتی بانک ناکات",

      audioTitle: "گوێ لە جیاوازیی دەنگ و شێوەزارەکە بگرە",
      audioSubtitle: "ببینە چۆن دەنگی سۆرانیی ئاسایی دەبێتە عەرەبی عێراقییەکی ئەوەندە سروشتی کە گەشتیار وا دەزانێت کارمەندەکەت خەڵکی بەغدایە!",
      kurdishAudioLabel: "🎙️ دەنگی سەرەکی بە سۆرانی",
      iraqiAudioLabel: "⚡ دەنگی دۆبلاژکراو بە عەرەبی عێراقی (Doblaj AI)",
      kurdishTranscript: "«بەخێربێن بۆ پێشانگاکەمان، نوێترین مۆدێلی جلوبەرگی هاوینەمان بۆ گەیشتووە بە داشکاندنی تایبەت بۆ ئەم هەفتەیە...»",
      iraqiTranscript: "«أهلاً وسهلاً بيكم بمعرضنا، وصلتنا أرقى الموديلات الصيفية بتخفيضات خاصة كلش لهالاسبوع، لتفوتكم الفرصة وتعالوا زورونا...»",

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

      calcTitle: "ژمێرەری قازانجی گەشتیاران بۆ دووکانەکەت",
      calcSubtitle: "واز لە خەمڵاندن بهێنە. ئەم دوو خلیسکێنەرەی خوارەوە بجوڵێنە بۆ ئەوەی بە تەواوی بزانیت چەند پارەی کاشی گەشتیارانی عەرەب دەبەخشیتە ڕکابەرەکانت هەموو هەفتەیەک.",
      calcSlider1Label: "قازانجی مامناوەند لە هەر گەشتیارێک:",
      calcSlider2Label: "ژمارەی گەشتیارە عەرەبەکان:",
      calcResultProfit: "داهاتی مانگانەی لەدەستچوو:",
      calcCostNote: "تێچووی سیستەم: تەنها $20 لە مانگێکدا. باقی قازانجی ساغە.",
      calcCtaBtn: "ئەم قازانجە بۆ دووکانەکەم زیاد بکە",

      painSectionTag: "زەنگی مەترسیی ناوچەیی",
      painHeadline: "کەلوپەلەکەت بێ کڕیار ماوەتەوە، لە کاتێکدا ڕکابەرەکانت پارەی گەشتیاران دەبەن.",
      painBody:
        "لە کاتێکدا تۆ لەسەر هەزاران دۆلار کەلوپەلی هاوینەی نەفرۆشراو دانیشتووی، ١٤ دووکانی تر لە سلێمانی و هەولێر زیرەکی دەستکرد بەکاردەهێنن و گەشتیارانی عەرەب ڕاستەوخۆ دەهێننە ناو پێشانگاکانیان.",
      mapTitle: "نەخشەی ڕاداری چالاکی دووکانەکان لە سلێمانی و هەولێر",
      mapSubtitle: "خاڵە لێدەرەکان ئەو ناوچانەن کە ئەم هەفتەیە زۆرترین ڤیدیۆی عەرەبییان بڵاوکردووەتەوە:",

      pricingAnchor: "کرێی وەرگێڕ و بێژەری دەنگی عەرەبی:",
      pricingAnchorOld: "$500 / مانگانە",
      pricingAnchorSave: "٩٦٪ پاشەکەوت بکە بە Doblaj AI",
      pricingTitle: "نرخی ڕزگارکردنی کاسبییەکەت",
      pricingSubtitle: "تەنها یەک فرۆش بە گەشتیارێکی عەرەب، تێچووی تەواوی مانگێکی ئەم سیستەمە دەردێنێتەوە.",
      billingMonthly: "مانگانە",
      billingAnnual: "ساڵانە (٢ مانگ بە دیاری 🎁)",

      decoyTitle: "دەستپێکی سنووردار (داو)",
      decoyPrice: isAnnual ? "$12" : "$15",
      decoyPeriod: "/مانگ",
      decoyLimit: "تەنها یەک ڤیدیۆ لە مانگێکدا",
      decoyItem1: "ڕیزبەندیی هێواش",
      decoyItem2: "کواڵێتی ئاسایی 720p",
      decoyItem3: "دەنگی سادە و بێ هەست",
      decoyCta: "تەنها ١ ڤیدیۆ ($15)",

      targetBadge: "🔥 پڕداواکراوترین — هەلی زێڕینی دووکاندار",
      targetTitle: "پلانی گەشەی بێسنوور",
      targetPrice: isAnnual ? "$16" : "$20",
      targetPeriod: "/مانگ",
      targetLimit: "ڤیدیۆی بێسنوور (تا ١٥ خولەک)",
      targetItem1: "⚡ خێرایی دەستبەجێ بەبێ وەستان",
      targetItem2: "✨ شێوەزاری عێراقیی پاراو و هەستی سروشتی",
      targetItem3: "🎥 کواڵێتی 4K Ultra-HD بۆ ئینستاگرام و تیکتۆک",
      targetItem4: "🗣️ جیاکردنەوەی خۆکارانەی دەنگ و پاراستنی میوزیک",
      targetMicroCopy: "💡 کەمترە لە قازانجی فرۆشتنی تەنها یەک تیشێرت!",
      targetCta: "ئێستا دەست بە پلانی $20 بێسنوور بکە",

      anchorTitle: "ئاژانس و کۆمپانیا",
      anchorPrice: isAnnual ? "$79" : "$99",
      anchorPeriod: "/مانگ",
      anchorLimit: "١٢٠ خولەک بۆ فرە-لق",
      anchorItem1: "ڕاڕەوی خێرای VIP بەرزترین لەپێشینە",
      anchorItem2: "ناسینەوەی فرە-قسەکەر لە یەک کاتدا",
      anchorItem3: "کڵۆنکردنی دەنگی تایبەتی کارمەندانت",
      anchorItem4: "بەستنەوە بە API و پشتگیریی بەردەوام",
      anchorCta: "پلانی کۆمپانیا ($99)",

      paymentTrust: "🔒 پارەدان بە دڵنیایی بە فاستپەی (FastPay)، FIB، زین کاش، ئاسیاحەواڵە، ڤیزا و ماستەرکارت.",

      faqTitle: "وەڵامی ئەو پرسیارانەی لە مێشکتدان",
      faqSubtitle: "بەر لەوەی دووکاندارەکەی تەنیشتت گەشتیارەکان بۆ لای خۆی ڕابکێشێت بیخوێنەرەوە.",

      faq1Q: "ناتوانم تەنها ژێرنووسی عەرەبیی بێبەرامبەر (نووسین) لەسەر ڤیدیۆکەم دابنێم؟",
      faq1A:
        "هیچ کەسێک لە ناو بازاڕی قەرەباڵغ یان لە کاتی سەیرکردنی خێرای تیکتۆک ناوەستێت بۆ خوێندنەوەی دەقی وردی ژێرنووس. گەشتیار کاتێک دەکڕێت کە گوێی لە دەنگێکی عەرەبی عێراقیی گەرم و ڕەسەن بێت کە بە شێوەزاری خۆی بەخێرهاتنی دەکات. ژێرنووس لە نیو چرکەدا فڕێ دەدرێتە سەرەوە، بەڵام دەنگی سروشتی کڕیار دێنێتە بەردەم مەنزەرەکەت!",

      faq2Q: "من کاسبکارم و شارەزایی بەرزی کۆمپیوتەرم نییە، ئایا ئەمە ئاڵۆز نییە بۆ من؟",
      faq2A:
        "پێویست ناکات ئەندازیاری پرۆگرامسازی بیت—تۆ کاسبکارێکی زیرەکیت. ئەگەر بزانیت چۆن لە وەتسئەپ ڤیدیۆ دەنێریت یان لە ئینستاگرام ستۆری دادەنێیت، لە ١٠ چرکەدا دەتوانیت Doblaj بەکاربهێنیت. تەنها ڤیدیۆکەت باردەکەیت، زیرەکی دەستکرد بە عەرەبی عێراقی قسەی پێدەکات و تۆ بڵاوی دەکەیتەوە. تایبەت بۆ کاسبکارانی سەرقاڵ دروستکراوە.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • ئۆستن، تەکساس، ویلایەتە یەکگرتووەکانی ئەمریکا",
      navFeatures: "جیاوازیی دەنگ",
      navCalculator: "ژمێرەری قازانج",
      navMap: "نەخشەی چالاک",
      navPricing: "نرخەکان",
      navFaq: "پرسیارە باوەکان",
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
      ctaHeroMassive: "ابدأ الآن فوراً (ربط الواتساب بـ ١٠ ثواني)",
      inputPlaceholder: "اكتب رقم الواتساب (+964 7XX...)",
      ctaPrimary: "اربط رقم الواتساب بـ ١٠ ثواني",
      ctaSubtext: "⚡ تجربة مجانية فورية • بدون الحاجة لبطاقة بنكية",

      audioTitle: "اسمع الفرق بين الصوت الكردي والدبلجة العراقية",
      audioSubtitle: "شوف شلون الصوت الكردي يتحول للهجة بغدادية حقيقية كأنما صاحب المحل ابن بغداد!",
      kurdishAudioLabel: "🎙️ الصوت الأصلي (سۆرانی)",
      iraqiAudioLabel: "⚡ الصوت المدبلج باللهجة العراقية (Doblaj AI)",
      kurdishTranscript: "«بەخێربێن بۆ پێشانگاکەمان، نوێترین مۆدێلی جلوبەرگی هاوینەمان بۆ گەیشتووە بە داشکاندنی تایبەت بۆ ئەم هەفتەیە...»",
      iraqiTranscript: "«أهلاً وسهلاً بيكم بمعرضنا، وصلتنا أرقى الموديلات الصيفية بتخفيضات خاصة كلش لهالاسبوع، لتفوتكم الفرصة وتعالوا زورونا...»",

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

      calcTitle: "حاسبة أرباح السياح لمحلك",
      calcSubtitle: "لتخمّن وتتحزر. حرك المؤشرات جوا وشوف بالضبط شكد فلوس كاش من السياح العرب د تخلي منافسيك ياخذوها منك كل اسبوع.",
      calcSlider1Label: "متوسط الربح الصافي من كل سائح:",
      calcSlider2Label: "عدد السياح العرب:",
      calcResultProfit: "الأرباح الشهرية الصافية الضائعة:",
      calcCostNote: "تكلفة النظام: فقط $20 شهرياً. باقي المبلغ أرباح صافية.",
      calcCtaBtn: "ضيف هاي الأرباح لمحلي",

      painSectionTag: "جرس إنذار محلي",
      painHeadline: "بينما بضاعتك نايمة بالمحل، منافسينك د ياخذون فلوس السياح.",
      painBody:
        "بينما أنت كاعد على بضاعة صيفية بآلاف الدولارات ما مباعة، اكو ١٤ محل ومعرض بالسليمانية وأربيل ديستعملون نظامنا ود يجيبون السياح العرب لمحلاتهم يومياً.",
      mapTitle: "خارطة الرادار الحية للمحلات في السليمانية وأربيل",
      mapSubtitle: "النقاط المضيئة تمثل أكثر الشوارع اللي دبلجت فيديوهات إعلانية هذا الأسبوع:",

      pricingAnchor: "تكلفة توظيف مترجم ومعلق صوتي عربي شهرياً:",
      pricingAnchorOld: "$500 / شهرياً",
      pricingAnchorSave: "وفّر ٩٦٪ فوراً مع Doblaj AI",
      pricingTitle: "أسعار خطة النجاة وزيادة المبيعات",
      pricingSubtitle: "بيعة وحدة لسائح عربي تطلعلك تكلفة اشتراك شهر كامل من هذا البرنامج.",
      billingMonthly: "شهرياً",
      billingAnnual: "سنوياً (شهران مجاناً 🎁)",

      decoyTitle: "الباقة التجريبية (فخ)",
      decoyPrice: isAnnual ? "$12" : "$15",
      decoyPeriod: "/شهر",
      decoyLimit: "فيديو واحد فقط شهرياً",
      decoyItem1: "معالجة بطيئة",
      decoyItem2: "دقة عادية 720p",
      decoyItem3: "صوت آلي بسيط",
      decoyCta: "فيديو واحد فقط ($15)",

      targetBadge: "🔥 الأكثر طلباً — خطة التوسع والنمو",
      targetTitle: "باقة المحلات الذكية",
      targetPrice: isAnnual ? "$16" : "$20",
      targetPeriod: "/شهر",
      targetLimit: "فيديوهات غير محدودة (حتى ١٥ دقيقة)",
      targetItem1: "⚡ أولوية قصوى ومعالجة فورية",
      targetItem2: "✨ لهجة عراقية بغدادية أصلية بمشاعر حقيقية",
      targetItem3: "🎥 تصدير بدقة 4K Ultra-HD للإنستغرام والتيك توك",
      targetItem4: "🗣️ عزل صوت الغرفة والموسيقى التصويرية تلقائياً",
      targetMicroCopy: "💡 تكلفتها أقل من ربح بيع تيشرت واحد بمحلك!",
      targetCta: "اشترك الآن بـ $20 للفيديوهات غير المحدودة",

      anchorTitle: "باقة الوكالات والشركات",
      anchorPrice: isAnnual ? "$79" : "$99",
      anchorPeriod: "/شهر",
      anchorLimit: "١٢٠ دقيقة للفروع المتعددة",
      anchorItem1: "معالجة VIP بأعلى سرعة سيرفرات",
      anchorItem2: "تمييز تلقائي لعدة متحدثين بالفيديو",
      anchorItem3: "استنساخ صوت كادرك الخاص",
      anchorItem4: "ربط برمجيات API ودعم فني مخصص",
      anchorCta: "باقة الوكالات ($99)",

      paymentTrust: "🔒 دفع آمن وسهل عبر فاست باي (FastPay)، زين كاش، FIB، آسيا حوالة، فيزا وماستركارد.",

      faqTitle: "إجابات على مخاوفك وترددك",
      faqSubtitle: "اقرأها قبل ما المحل اللي بصفك يسحب كل سياح شارعكم.",

      faq1Q: "ليش ما أحط ترجمة كتابية (Subtitles) مجانية على الفيديو وخلاص؟",
      faq1A:
        "محد يفتر بالسوق المزدحم أو يقلب بالتيك توك ويكعد يقرا كتابة ناعمة. السائح العراقي يشتري من يسمع صوت عراقي حقيقي ولهجة بغدادية مألوفة ترحب بيه مباشرة. الكتابة الناس تتخطاها بـ ٠.٥ ثانية، بس الصوت العراقي الطبيعي يسحب الزبون لمحلك بثواني.",

      faq2Q: "أني صاحب محل مو مبرمج، هل البرنامج صعب ومعقد عليّ؟",
      faq2A:
        "ما تحتاج تكون خبير تقني—أنت صاحب عمل ذكي. إذا تعرف تدز فيديو بالواتساب أو تنشر ستوري بالانستغرام، تكدر تستعمل Doblaj بـ ١٠ ثواني. ترفع الفيديو الكردي، الذكاء الاصطناعي يدبلجه باللهجة العراقية، وتنشره. مصمم خصيصاً لأصحاب المحلات المشغولين اللي يريدون مبيعات بدون دوخة رأس.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • أوستن، تكساس، الولايات المتحدة",
      navFeatures: "مقارنة الصوت",
      navCalculator: "حاسبة الأرباح",
      navMap: "الخارطة الحية",
      navPricing: "الأسعار",
      navFaq: "الأسئلة الشائعة",
      navLogin: "لوحة التحكم",
      navStart: "ابدأ الآن",
    },
    en: {
      badge: "🚨 ATTENTION: SULAIMANIYAH & ERBIL RETAIL OWNERS",
      heroHeadlineStart: "The local market is frozen.",
      heroHeadlineHighlight: "The Arab tourists are spending billions of dinars.",
      heroHeadlineEnd: "Which market is your store talking to?",
      heroSub:
        "Stop waiting for delayed salaries. With our AI system, instantly dub your store's videos into Iraqi Arabic and turn the tourists walking past your door into real paying customers.",
      ctaHeroMassive: "Start Immediately (Link WhatsApp in 10 Seconds)",
      inputPlaceholder: "Enter WhatsApp number (+964 7XX...)",
      ctaPrimary: "Link My WhatsApp in 10 Seconds",
      ctaSubtext: "⚡ 100% Free Demo • No credit card required to test",

      audioTitle: "Hear The Dialect Precision",
      audioSubtitle: "Listen to how raw Kurdish promotional video audio transforms into friendly Baghdad dialect that tourists instantly trust:",
      kurdishAudioLabel: "🎙️ Original Kurdish Sorani",
      iraqiAudioLabel: "⚡ Dubbed Iraqi Arabic (Doblaj AI)",
      kurdishTranscript: "«Welcome to our showroom! The latest summer collection has arrived with special promotional discounts for this week...»",
      iraqiTranscript: "«Welcome everyone to our showroom! Top summer collections have arrived with huge discounts just for this week, don't miss out...»",

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

      calcTitle: "Tourist Cash Lift Calculator",
      calcSubtitle: "Stop guessing. Move the sliders below to see exactly how much Arab cash you are letting your competitors steal every single week.",
      calcSlider1Label: "Average Profit per Arab Customer:",
      calcSlider2Label: "Number of Arab Customers:",
      calcResultProfit: "Monthly Lost Tourist Revenue:",
      calcCostNote: "System Cost: Only $20/mo. The rest is 100% pure profit.",
      calcCtaBtn: "Add This Profit to My Store",

      painSectionTag: "TERRITORIAL ALERT",
      painHeadline: "While you sit on unsold inventory, your competitors are taking the tourist cash.",
      painBody:
        "While you are sitting on thousands of dollars in unsold stock, 14 other retail shops in Sulaymaniyah and Erbil are already using our AI to bring Arab tourists directly into their showrooms.",
      mapTitle: "Live Retail Radar Map (Sulaymaniyah & Erbil)",
      mapSubtitle: "Active pulsing nodes represent retail corridors dubbing videos this week:",

      pricingAnchor: "Hiring a human Arabic voice translator:",
      pricingAnchorOld: "$500 / month",
      pricingAnchorSave: "Save 96% with Doblaj AI",
      pricingTitle: "The Survival Pricing",
      pricingSubtitle: "Just one sale to an Arab tourist pays for an entire month of this system.",
      billingMonthly: "Monthly",
      billingAnnual: "Annual (2 Months Free 🎁)",

      decoyTitle: "Decoy Starter",
      decoyPrice: isAnnual ? "$12" : "$15",
      decoyPeriod: "/mo",
      decoyLimit: "Strict Limit: 1 Single Video / month",
      decoyItem1: "Slow queue processing",
      decoyItem2: "Standard 720p export",
      decoyItem3: "Basic mechanical voice",
      decoyCta: "Get 1 Video ($15)",

      targetBadge: "🔥 MOST POPULAR — UNLIMITED EXPANSION",
      targetTitle: "Retail Growth Target",
      targetPrice: isAnnual ? "$16" : "$20",
      targetPeriod: "/mo",
      targetLimit: "Unlimited Videos (Up to 15 mins total)",
      targetItem1: "⚡ Priority instant processing",
      targetItem2: "✨ Premium authentic Iraqi dialect & emotion",
      targetItem3: "🎥 4K Ultra-HD export for Instagram & TikTok",
      targetItem4: "🗣️ Preserves original background music & room audio",
      targetMicroCopy: "💡 Costs less than the profit of selling ONE single t-shirt.",
      targetCta: "Claim $20 Unlimited Access Now",

      anchorTitle: "Commercial Agency",
      anchorPrice: isAnnual ? "$79" : "$99",
      anchorPeriod: "/mo",
      anchorLimit: "120 Minutes Multi-Branch Power",
      anchorItem1: "Dedicated VIP processing queue",
      anchorItem2: "Unlimited multi-speaker detection",
      anchorItem3: "Custom voice cloning for your staff",
      anchorItem4: "Direct API + 24/7 priority support",
      anchorCta: "Get Agency Tier ($99)",

      paymentTrust: "🔒 Pay securely with FastPay, FIB, ZainCash, AsiaHawala, Visa, or Mastercard.",

      faqTitle: "Frequently Answered Objections",
      faqSubtitle: "Read before your competitor on your street takes your tourist customers.",

      faq1Q: "Can't I just put free Arabic subtitles (text) on my Kurdish videos?",
      faq1A:
        "Nobody walking through a noisy bazaar or rapidly scrolling TikTok stops to read small text subtitles while shopping. Tourists buy with their ears when they hear a friendly, authentic Iraqi voice greeting them directly in their own Baghdad dialect. Subtitles get skipped in 0.5 seconds; native audio dubbing turns scrolling tourists into paying in-store customers instantly.",

      faq2Q: "I'm just a shopkeeper, not a tech expert. Is this too complicated for me?",
      faq2A:
        "You don't need to be a software engineer—you're a smart business owner. If you know how to send a video on WhatsApp or post a story on Instagram, you can use Doblaj in 10 seconds. You simply upload your video, our AI speaks it in natural Iraqi Arabic, and you post it. It was built specifically for busy Kurdish shop owners who want sales, not tech headaches.",

      footerLegal: "FIXDAI LLC (d/b/a Doblaj) • Austin, TX, USA",
      navFeatures: "Voice Demo",
      navCalculator: "ROI Calculator",
      navMap: "Active Map",
      navPricing: "Pricing",
      navFaq: "FAQ",
      navLogin: "Dashboard",
      navStart: "Start Now",
    },
  }[lang];

  return (
    <div
      dir={isRTL ? "rtl" : "ltr"}
      className={`min-h-screen bg-[#040407] text-[#cfcfd3] ${isRTL ? "font-kurdish" : "font-sans"} antialiased selection:bg-emerald-500/25 selection:text-emerald-300 relative overflow-x-hidden`}
    >
      {/* Dynamic Ambient Background Beams & Mesh Glows */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute top-[-10%] left-[20%] w-[600px] h-[600px] rounded-full bg-emerald-600/10 blur-[140px] animate-pulse"></div>
        <div className="absolute top-[30%] right-[-5%] w-[500px] h-[500px] rounded-full bg-rose-600/[0.07] blur-[160px]"></div>
        <div className="absolute bottom-[10%] left-[-10%] w-[700px] h-[700px] rounded-full bg-emerald-500/[0.08] blur-[180px]"></div>
        {/* Subtle Cyber Grid */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-60"></div>
      </div>

      {/* Sticky Tactical Header */}
      <nav className="fixed top-0 w-full z-50 bg-[#07070b]/85 backdrop-blur-2xl border-b border-white/[0.07] shadow-[0_4px_30px_rgba(0,0,0,0.8)]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-10 flex justify-between items-center h-20">
          {/* Brand Logo */}
          <Link to="/" className="flex items-center gap-3.5 group">
            <div className="relative">
              <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-emerald-400 via-emerald-500 to-teal-700 p-0.5 shadow-[0_0_25px_rgba(16,185,129,0.4)] group-hover:scale-105 transition-all duration-300">
                <div className="w-full h-full bg-[#07070a] rounded-[14px] flex items-center justify-center">
                  <span className="text-emerald-400 font-black text-xl tracking-tighter">DB</span>
                </div>
              </div>
              <span className="absolute -top-1 -right-1 w-3 h-3 bg-emerald-400 rounded-full border-2 border-[#07070b] animate-ping"></span>
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="text-2xl font-black text-[#fafafa] tracking-tight group-hover:text-emerald-400 transition-colors">
                  Doblaj
                </span>
                <span className="text-[9px] uppercase px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-mono font-bold">
                  AI v2.4
                </span>
              </div>
              <span className="text-[10px] font-mono uppercase tracking-widest text-emerald-400/80 font-bold">
                Retail Growth System
              </span>
            </div>
          </Link>

          {/* Action Buttons & Language Switcher (No Escape Hatch Nav Links) */}
          <div className="flex items-center gap-3.5">
            {/* Language Switch */}
            <div className="flex items-center bg-[#111218] border border-white/[0.08] rounded-xl p-1 text-xs shadow-inner">
              <button
                onClick={() => setLang("ckb")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "ckb"
                    ? "bg-emerald-500 text-[#040407] shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                    : "text-[#a1a1aa] hover:text-white"
                }`}
              >
                سۆرانی
              </button>
              <button
                onClick={() => setLang("ar")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "ar"
                    ? "bg-emerald-500 text-[#040407] shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                    : "text-[#a1a1aa] hover:text-white"
                }`}
              >
                عربي
              </button>
              <button
                onClick={() => setLang("en")}
                className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                  lang === "en"
                    ? "bg-emerald-500 text-[#040407] shadow-[0_0_12px_rgba(16,185,129,0.5)]"
                    : "text-[#a1a1aa] hover:text-white"
                }`}
              >
                EN
              </button>
            </div>

            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="relative group overflow-hidden px-5 py-2.5 sm:px-6 sm:py-3 rounded-xl bg-gradient-to-r from-emerald-400 via-emerald-500 to-teal-500 text-[#040407] text-xs sm:text-sm font-black uppercase tracking-wider shadow-[0_0_30px_rgba(16,185,129,0.4)] transition-all duration-300 transform hover:scale-[1.03] active:scale-[0.98]"
            >
              <span className="relative z-10 flex items-center gap-2 font-bold">
                <span>⚡</span>
                <span>{isSignedIn ? t.navLogin : t.navStart}</span>
              </span>
              <div className="absolute inset-0 bg-white/20 transform -skew-x-12 -translate-x-full group-hover:translate-x-full transition-transform duration-700"></div>
            </Link>
          </div>
        </div>
      </nav>

      {/* SECTION 1: THE HERO SECTION (Extreme Contrast & Lethal Framing) */}
      <section id="contrast-hero" className="relative pt-36 sm:pt-44 pb-20 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto z-10">
        {/* Warning Indicator */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="flex justify-center mb-8"
        >
          <div className="inline-flex items-center gap-3 px-5 py-2.5 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs sm:text-sm font-black tracking-wide shadow-[0_0_30px_rgba(244,63,94,0.2)]">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500 shadow-[0_0_10px_#f43f5e]"></span>
            </span>
            <span>{t.badge}</span>
          </div>
        </motion.div>

        {/* Shock Headline */}
        <motion.div
          initial={{ opacity: 0, y: 25 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-center max-w-4xl mx-auto mb-12 space-y-5"
        >
          <h1 className="text-3xl sm:text-5xl lg:text-6xl font-black text-white leading-[1.3]">
            {/* The Cold Pain: Dead, harsh, flat light gray representing boring reality */}
            <span className="text-[#9ca3af] block mb-3 text-2xl sm:text-4xl lg:text-5xl font-extrabold tracking-normal">
              {t.heroHeadlineStart}
            </span>
            {/* The Target Outcome: ONLY this is glowing Teal/Emerald (Money/Escape) */}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-300 via-emerald-400 to-teal-300 block mb-4 text-3xl sm:text-5xl lg:text-6xl font-black drop-shadow-[0_0_45px_rgba(16,185,129,0.45)]">
              {t.heroHeadlineHighlight}
            </span>
            {/* The Closing Question: Crisp pure white */}
            <span className="text-white block text-2xl sm:text-4xl lg:text-5xl font-black">
              {t.heroHeadlineEnd}
            </span>
          </h1>

          {/* Subheadline: 1.5x Line-height breathing room for effortless reading */}
          <p className="text-base sm:text-xl lg:text-2xl text-zinc-300 max-w-3xl mx-auto font-medium leading-[2.1] sm:leading-[2.3] pt-4 px-2">
            {t.heroSub}
          </p>
        </motion.div>

        {/* LETHAL SPLIT SCREEN COMPARISON (Frozen Store vs Active Tourist Wealth) */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3 }}
          className="grid lg:grid-cols-2 gap-8 items-stretch"
        >
          {/* Left: The Dark / Pain Store */}
          <div className="bg-gradient-to-b from-[#130b0f] via-[#0d070a] to-[#070507] border border-rose-900/40 rounded-3xl p-8 sm:p-10 flex flex-col justify-between relative overflow-hidden shadow-2xl group hover:border-rose-700/60 transition-all duration-300">
            <div className="absolute top-0 right-0 left-0 h-1.5 bg-gradient-to-r from-rose-700 to-rose-500"></div>
            <div>
              <div className="flex justify-between items-center mb-6">
                <span className="px-4 py-1.5 rounded-full text-xs sm:text-sm font-black uppercase tracking-wider bg-rose-500/15 text-rose-400 border border-rose-500/30 flex items-center gap-2">
                  <span>{t.splitLeftStatus}</span>
                  <span>🥀</span>
                </span>
                <span className="text-xs font-mono text-rose-400/60 uppercase font-bold">STATUS: FROZEN</span>
              </div>
              <h3 className="text-xl sm:text-2xl font-black text-[#fafafa] mb-6">
                {t.splitLeftTitle}
              </h3>
              <ul className="space-y-4 text-sm sm:text-base text-[#cfcfd3] mb-8 font-medium">
                <li className="flex items-start gap-3 p-3 rounded-xl bg-black/40 border border-rose-900/20">
                  <span className="text-rose-500 font-black text-lg">✕</span>
                  <span className="leading-snug">{t.splitLeftItem1}</span>
                </li>
                <li className="flex items-start gap-3 p-3 rounded-xl bg-black/40 border border-rose-900/20">
                  <span className="text-rose-500 font-black text-lg">✕</span>
                  <span className="leading-snug">{t.splitLeftItem2}</span>
                </li>
                <li className="flex items-start gap-3 p-3 rounded-xl bg-black/40 border border-rose-900/20">
                  <span className="text-rose-500 font-black text-lg">✕</span>
                  <span className="leading-snug">{t.splitLeftItem3}</span>
                </li>
              </ul>
            </div>
            <div className="p-5 rounded-2xl bg-black/70 border border-rose-900/50 text-center">
              <div className="text-xs uppercase font-black text-rose-400 tracking-wider mb-1">
                Tourist Revenue Result
              </div>
              <div className="text-3xl sm:text-4xl font-black text-rose-500 font-mono">
                {t.splitLeftMetric}
              </div>
            </div>
          </div>

          {/* Right: The Wealth / Escape Store */}
          <div className="bg-gradient-to-b from-[#0c1f15] via-[#081710] to-[#040e09] border-2 border-emerald-500 rounded-3xl p-8 sm:p-10 flex flex-col justify-between relative overflow-hidden shadow-[0_0_60px_rgba(16,185,129,0.25)] group hover:border-emerald-400 transition-all duration-300">
            <div className="absolute top-0 right-0 left-0 h-2 bg-gradient-to-r from-emerald-400 via-teal-300 to-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.8)]"></div>
            <div>
              <div className="flex justify-between items-center mb-6">
                <span className="px-4 py-1.5 rounded-full text-xs sm:text-sm font-black uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.3)] flex items-center gap-2">
                  <span>{t.splitRightStatus}</span>
                  <span>💰</span>
                </span>
                <span className="text-xs font-mono text-emerald-400/80 uppercase font-bold flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                  <span>ACTIVE REVENUE</span>
                </span>
              </div>
              <h3 className="text-xl sm:text-2xl font-black text-[#fafafa] mb-6">
                {t.splitRightTitle}
              </h3>
              <ul className="space-y-4 text-sm sm:text-base text-[#fafafa] mb-8 font-semibold">
                <li className="flex items-start gap-3 p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30">
                  <span className="text-emerald-400 font-black text-lg">✓</span>
                  <span className="leading-snug">{t.splitRightItem1}</span>
                </li>
                <li className="flex items-start gap-3 p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30">
                  <span className="text-emerald-400 font-black text-lg">✓</span>
                  <span className="leading-snug">{t.splitRightItem2}</span>
                </li>
                <li className="flex items-start gap-3 p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30">
                  <span className="text-emerald-400 font-black text-lg">✓</span>
                  <span className="leading-snug">{t.splitRightItem3}</span>
                </li>
              </ul>
            </div>
            <div className="p-5 rounded-2xl bg-[#040907]/90 border border-emerald-500/60 text-center shadow-[0_0_25px_rgba(16,185,129,0.2)]">
              <div className="text-xs uppercase font-black text-emerald-400 tracking-wider mb-1">
                Tourist Revenue Added
              </div>
              <div className="text-3xl sm:text-4xl font-black text-emerald-400 font-mono drop-shadow-[0_0_20px_rgba(16,185,129,0.5)]">
                {t.splitRightMetric}
              </div>
            </div>
          </div>
        </motion.div>

        {/* MASSIVE GLOWING HERO CTA BUTTON (The Release Valve) */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="mt-12 flex flex-col items-center justify-center text-center max-w-3xl mx-auto z-20"
        >
          <Link
            to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
            className="w-full sm:w-auto relative group overflow-hidden px-8 sm:px-14 py-5 sm:py-6 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-400 to-emerald-400 hover:from-emerald-300 hover:to-teal-300 text-[#040407] text-lg sm:text-2xl font-black shadow-[0_0_60px_rgba(16,185,129,0.55)] hover:shadow-[0_0_80px_rgba(16,185,129,0.75)] transition-all duration-300 transform hover:scale-[1.03] active:scale-[0.98] flex items-center justify-center gap-3 border-2 border-emerald-300/60"
          >
            <span className="relative z-10 flex items-center gap-3 font-black">
              <span className="text-2xl sm:text-3xl">⚡</span>
              <span>{t.ctaHeroMassive}</span>
            </span>
            <div className="absolute inset-0 bg-white/30 transform -skew-x-12 -translate-x-full group-hover:translate-x-full transition-transform duration-700"></div>
          </Link>

          {/* Repositioned bold psychological rational justification directly under CTA */}
          <p className="mt-5 text-sm sm:text-base lg:text-lg font-bold text-emerald-300/95 max-w-2xl mx-auto leading-relaxed px-4 drop-shadow-[0_0_20px_rgba(16,185,129,0.25)]">
            {t.splitBottomNote}
          </p>
        </motion.div>
      </section>

      {/* SECTION 2: INTERACTIVE "HEAR THE DIFFERENCE" LIVE DUBBING PREVIEW PLAYER */}
      <section id="voice-demo" className="py-24 px-4 sm:px-6 lg:px-10 bg-[#07080d] border-y border-white/[0.08] relative z-10">
        <div className="max-w-5xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-14 space-y-3">
            <div className="inline-block px-4 py-1.5 rounded-full text-xs font-black uppercase tracking-widest bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              {isRTL ? "کواڵێتی دەنگ و شێوەزار" : "ACOUSTIC PRECISION ENGINE"}
            </div>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-black text-[#fafafa] tracking-tight">
              {t.audioTitle}
            </h2>
            <p className="text-sm sm:text-base text-[#a1a1aa] font-medium leading-relaxed">
              {t.audioSubtitle}
            </p>
          </div>

          {/* Interactive Player Console */}
          <div className="bg-[#0d1017] rounded-3xl p-6 sm:p-10 border-2 border-white/[0.1] shadow-2xl relative overflow-hidden">
            {/* Audio Mode Tabs */}
            <div className="flex flex-col sm:flex-row gap-3 mb-8 bg-[#07090e] p-2 rounded-2xl border border-white/[0.08]">
              <button
                onClick={() => { setActiveAudioTab("kurdish"); setAudioProgress(0); }}
                className={`flex-1 py-4 px-6 rounded-xl font-black text-sm transition-all flex items-center justify-center gap-3 ${
                  activeAudioTab === "kurdish"
                    ? "bg-[#181a24] text-rose-300 border border-rose-500/40 shadow-lg"
                    : "text-[#a1a1aa] hover:text-white"
                }`}
              >
                <span>{t.kurdishAudioLabel}</span>
              </button>
              <button
                onClick={() => { setActiveAudioTab("iraqi"); setAudioProgress(0); }}
                className={`flex-1 py-4 px-6 rounded-xl font-black text-sm transition-all flex items-center justify-center gap-3 ${
                  activeAudioTab === "iraqi"
                    ? "bg-gradient-to-r from-emerald-500 to-teal-500 text-[#040407] shadow-[0_0_25px_rgba(16,185,129,0.5)] scale-[1.01]"
                    : "text-[#a1a1aa] hover:text-white"
                }`}
              >
                <span>{t.iraqiAudioLabel}</span>
              </button>
            </div>

            {/* Simulated Live Waveform & Playback Visualizer */}
            <div className="bg-[#06070b] p-6 sm:p-8 rounded-2xl border border-white/[0.08] mb-8 space-y-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setIsPlayingAudio(!isPlayingAudio)}
                    className={`w-12 h-12 rounded-2xl flex items-center justify-center text-xl transition-all shadow-lg ${
                      activeAudioTab === "iraqi"
                        ? "bg-emerald-500 text-[#040407] hover:bg-emerald-400 shadow-emerald-500/30"
                        : "bg-rose-500 text-white hover:bg-rose-400 shadow-rose-500/30"
                    }`}
                  >
                    {isPlayingAudio ? "⏸" : "▶"}
                  </button>
                  <div>
                    <div className="text-sm font-extrabold text-[#fafafa]">
                      {activeAudioTab === "iraqi" ? "Iraqi Dialect Stream (AI Synthesized)" : "Kurdish Original Audio"}
                    </div>
                    <div className="text-xs font-mono text-emerald-400 font-bold">
                      24-bit 48kHz • Natural Iraqi Cadence Engine
                    </div>
                  </div>
                </div>
                <div className="text-xs font-mono text-[#a1a1aa] font-bold">
                  00:0{Math.floor(audioProgress / 20)} / 00:05
                </div>
              </div>

              {/* Dynamic Spectrum Waveform Bars */}
              <div className="flex items-center justify-between gap-1 sm:gap-1.5 h-16 px-2">
                {[18, 35, 60, 85, 45, 90, 75, 40, 65, 95, 80, 50, 70, 100, 85, 60, 45, 80, 65, 40, 90, 75, 55, 30].map((h, i) => (
                  <div
                    key={i}
                    style={{
                      height: isPlayingAudio ? `${Math.max(15, (h * (0.5 + Math.sin((audioProgress + i * 10) / 10) * 0.5)))}%` : `${h * 0.3}%`,
                    }}
                    className={`flex-1 rounded-full transition-all duration-150 ${
                      activeAudioTab === "iraqi"
                        ? i * 4.1 <= audioProgress ? "bg-gradient-to-t from-emerald-500 to-teal-300 shadow-[0_0_8px_#10b981]" : "bg-emerald-950/40"
                        : i * 4.1 <= audioProgress ? "bg-rose-500 shadow-[0_0_8px_#f43f5e]" : "bg-rose-950/40"
                    }`}
                  ></div>
                ))}
              </div>

              {/* Spoken Transcript Box */}
              <div className="p-4 rounded-xl bg-[#0e111a] border border-white/[0.06] text-xs sm:text-sm font-medium text-[#e4e4e7] leading-relaxed">
                <span className="text-[#8e8e9c] text-xs block mb-1 font-bold">
                  {isRTL ? "دەقی قسەکراو لە ڤیدیۆکەدا:" : "Spoken Video Dialogue:"}
                </span>
                <span className={activeAudioTab === "iraqi" ? "text-emerald-300 font-bold" : "text-rose-200"}>
                  {activeAudioTab === "iraqi" ? t.iraqiTranscript : t.kurdishTranscript}
                </span>
              </div>
            </div>

            <div className="text-center">
              <span className="text-xs font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-4 py-2 rounded-full font-bold">
                ⚡ Tested with Arab tourists across Baghdad, Basra, and Najaf with 99.4% dialect comprehension
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 3: INTERACTIVE ROI / PROFIT LIFT SIMULATOR */}
      <section id="roi-calculator" className="py-24 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto z-10">
        <div className="text-center max-w-3xl mx-auto mb-16 space-y-3">
          <div className="inline-block px-4 py-1.5 rounded-full text-xs font-black uppercase tracking-widest bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            {isRTL ? "داهات و قازانجی ڕاستەقینە" : "PROFIT PROJECTION"}
          </div>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-black text-[#fafafa] tracking-tight">
            {t.calcTitle}
          </h2>
          <p className="text-base sm:text-lg text-zinc-300 font-medium leading-relaxed max-w-2xl mx-auto">
            {t.calcSubtitle}
          </p>
        </div>

        <div className="grid lg:grid-cols-12 gap-8 items-stretch bg-[#0d1017] rounded-3xl p-6 sm:p-10 border border-white/[0.1] shadow-2xl">
          {/* Sliders Input Panel (Right column in RTL, 7 Cols) */}
          <div className="lg:col-span-7 space-y-8 flex flex-col justify-center">
            {/* Slider 1: Average Profit per Arab Customer */}
            <div className="space-y-3 bg-[#08090f] p-5 rounded-2xl border border-white/[0.06]">
              <div className="flex justify-between items-center text-sm sm:text-base font-bold text-white">
                <span>{t.calcSlider1Label}</span>
                <span className="text-xl sm:text-2xl font-black text-emerald-400 font-mono">
                  {avgProfitPerCustomer.toLocaleString()} {isRTL ? "دینار" : "IQD"}
                </span>
              </div>
              <input
                type="range"
                min="10000"
                max="100000"
                step="5000"
                value={avgProfitPerCustomer}
                onChange={(e) => setAvgProfitPerCustomer(Number(e.target.value))}
                className="w-full h-3 bg-[#030407] rounded-lg appearance-none cursor-pointer accent-emerald-400"
              />
              <div className="flex justify-between text-xs font-mono text-[#71717a]">
                <span>{isRTL ? "١٠,٠٠٠ دینار" : "10,000 IQD"}</span>
                <span>{isRTL ? "٥٠,٠٠٠ دینار" : "50,000 IQD"}</span>
                <span>{isRTL ? "١٠٠,٠٠٠ دینار" : "100,000 IQD"}</span>
              </div>
            </div>

            {/* Slider 2: Number of Arab Customers */}
            <div className="space-y-3 bg-[#08090f] p-5 rounded-2xl border border-white/[0.06]">
              <div className="flex justify-between items-center text-sm sm:text-base font-bold text-white">
                <span>{t.calcSlider2Label}</span>
                <span className="text-xl sm:text-2xl font-black text-emerald-400 font-mono">
                  {touristCustomers} {isRTL ? "کڕیار" : "customers"}
                </span>
              </div>
              <input
                type="range"
                min="1"
                max="50"
                step="1"
                value={touristCustomers}
                onChange={(e) => setTouristCustomers(Number(e.target.value))}
                className="w-full h-3 bg-[#030407] rounded-lg appearance-none cursor-pointer accent-emerald-400"
              />
              <div className="flex justify-between text-xs font-mono text-[#71717a]">
                <span>{isRTL ? "١ کڕیار" : "1 customer"}</span>
                <span>{isRTL ? "٢٥ کڕیار" : "25 customers"}</span>
                <span>{isRTL ? "٥٠ کڕیار" : "50 customers"}</span>
              </div>
            </div>
          </div>

          {/* Result Output Card (Left column in RTL, 5 Cols) */}
          <div className="lg:col-span-5 bg-gradient-to-b from-[#112419] to-[#0a160f] rounded-2xl p-6 sm:p-8 border-2 border-emerald-500/80 shadow-[0_0_50px_rgba(16,185,129,0.25)] flex flex-col justify-between text-center space-y-6">
            <div className="space-y-3">
              {/* Sub-text in White / light gray */}
              <div className="text-sm sm:text-base font-bold text-zinc-300 tracking-normal">
                {t.calcResultProfit}
              </div>
              {/* Massive Glowing Green Text */}
              <div className="text-4xl sm:text-5xl lg:text-6xl font-black text-emerald-400 font-mono tracking-tight drop-shadow-[0_0_35px_rgba(16,185,129,0.55)]">
                +{totalCalculatedProfitIQD.toLocaleString()} {isRTL ? "دینار" : "IQD"}
              </div>
              {/* Small White Text underneath */}
              <p className="text-xs sm:text-sm font-medium text-zinc-300/90 leading-relaxed pt-2">
                {t.calcCostNote}
              </p>
            </div>

            {/* Massive Glowing Green CTA Button */}
            <Link
              to={isSignedIn ? "/dubbing" : `/sign-up?redirect_url=${encodeURIComponent('/dubbing')}`}
              className="block w-full py-4 sm:py-5 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-400 to-emerald-400 hover:from-emerald-300 hover:to-teal-300 text-[#040407] font-black text-base sm:text-lg shadow-[0_0_35px_rgba(16,185,129,0.5)] transition-all transform hover:scale-[1.02] active:scale-[0.98]"
            >
              {t.calcCtaBtn}
            </Link>
          </div>
        </div>
      </section>

      {/* SECTION 4: THE PRICING GUILLOTINE (Decoy Effect & Anchoring) */}
      <section id="pricing" className="py-24 px-4 sm:px-6 lg:px-10 max-w-7xl mx-auto z-10">
        <div className="text-center max-w-3xl mx-auto mb-16 space-y-4">
          {/* Top Crossed-out Human Anchor */}
          <div className="inline-flex flex-col sm:flex-row items-center gap-2 p-3.5 sm:px-6 sm:py-2.5 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-sm font-bold shadow-lg">
            <span className="text-[#a1a1aa]">{t.pricingAnchor}</span>
            <span className="line-through text-rose-400 font-extrabold text-base">{t.pricingAnchorOld}</span>
            <span className="text-emerald-400 bg-emerald-500/20 px-3 py-0.5 rounded-full text-xs font-black">
              {t.pricingAnchorSave}
            </span>
          </div>

          <h2 className="text-3xl sm:text-5xl font-black text-[#fafafa] tracking-tight">
            {t.pricingTitle}
          </h2>
          <p className="text-base sm:text-lg text-emerald-400 font-bold">
            {t.pricingSubtitle}
          </p>

          {/* Billing Cycle Switch */}
          <div className="flex justify-center items-center gap-3 pt-4">
            <span className={`text-xs font-bold ${!isAnnual ? "text-white" : "text-[#71717a]"}`}>{t.billingMonthly}</span>
            <button
              onClick={() => setIsAnnual(!isAnnual)}
              className="w-14 h-7 bg-[#161922] rounded-full p-1 border border-white/[0.1] transition-colors relative"
            >
              <div className={`w-5 h-5 rounded-full bg-emerald-400 shadow-md transition-transform transform ${isAnnual ? (isRTL ? "-translate-x-7" : "translate-x-7") : ""}`}></div>
            </button>
            <span className={`text-xs font-bold ${isAnnual ? "text-emerald-400" : "text-[#71717a]"}`}>{t.billingAnnual}</span>
          </div>
        </div>

        {/* 3 Manipulated Tiers (RTL Reading Flow: Anchor ($99) on Far Right -> Target ($20) in Middle -> Decoy ($15) on Far Left) */}
        <div className="grid lg:grid-cols-3 gap-8 items-center max-w-6xl mx-auto">
          {/* Card 1: The Anchor ($99 - Agency / Company Plan) -> First Child = Far Right in RTL */}
          <div className="bg-[#0a0c12] rounded-3xl p-6 sm:p-8 border border-white/[0.08] flex flex-col justify-between shadow-2xl">
            <div>
              <div className="text-xs uppercase font-mono text-[#a1a1aa] font-bold mb-2">
                {t.anchorTitle}
              </div>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-4xl font-extrabold text-[#fafafa]">{t.anchorPrice}</span>
                <span className="text-xs text-[#71717a]">{t.anchorPeriod}</span>
              </div>
              <div className="text-xs font-bold text-[#a1a1aa] mb-6 bg-white/[0.05] px-3 py-1 rounded-lg inline-block">
                🏢 {t.anchorLimit}
              </div>
              <ul className="space-y-3 text-xs text-[#cfcfd3] mb-8 font-medium">
                <li className="flex items-center gap-2"><span className="text-emerald-400 font-bold">✓</span> {t.anchorItem1}</li>
                <li className="flex items-center gap-2"><span className="text-emerald-400 font-bold">✓</span> {t.anchorItem2}</li>
                <li className="flex items-center gap-2"><span className="text-emerald-400 font-bold">✓</span> {t.anchorItem3}</li>
                <li className="flex items-center gap-2"><span className="text-emerald-400 font-bold">✓</span> {t.anchorItem4}</li>
              </ul>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=creator" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=creator')}`}
              className="w-full py-3.5 rounded-xl border border-white/[0.15] text-center text-xs font-bold text-[#fafafa] hover:bg-white/[0.06] transition-colors block"
            >
              {t.anchorCta}
            </Link>
          </div>

          {/* Card 2: The Target ($20 - Most Popular) -> Middle Child */}
          <div className="bg-gradient-to-b from-[#12281a] via-[#0b1b11] to-[#06100a] rounded-3xl p-8 sm:p-10 border-2 border-emerald-400 flex flex-col justify-between relative shadow-[0_0_60px_rgba(16,185,129,0.3)] transform lg:-translate-y-4">
            <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1.5 bg-gradient-to-r from-emerald-400 to-teal-400 text-[#040407] text-xs font-black uppercase rounded-full shadow-[0_0_20px_rgba(16,185,129,0.8)] whitespace-nowrap">
              {t.targetBadge}
            </div>
            <div>
              <div className="text-xs uppercase font-mono text-emerald-400 font-black tracking-wider mb-2">
                {t.targetTitle}
              </div>
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-6xl font-black text-[#fafafa] tracking-tight">{t.targetPrice}</span>
                <span className="text-sm font-bold text-[#a1a1aa]">{t.targetPeriod}</span>
              </div>
              <div className="text-sm font-black text-emerald-300 mb-6 bg-emerald-500/20 px-3.5 py-1.5 rounded-xl inline-block border border-emerald-500/40">
                ✨ {t.targetLimit}
              </div>
              <ul className="space-y-3.5 text-sm font-semibold text-[#fafafa] mb-6">
                <li className="flex items-center gap-2.5"><span className="text-emerald-400 font-black">✓</span> {t.targetItem1}</li>
                <li className="flex items-center gap-2.5"><span className="text-emerald-400 font-black">✓</span> {t.targetItem2}</li>
                <li className="flex items-center gap-2.5"><span className="text-emerald-400 font-black">✓</span> {t.targetItem3}</li>
                <li className="flex items-center gap-2.5"><span className="text-emerald-400 font-black">✓</span> {t.targetItem4}</li>
              </ul>
              <div className="p-3.5 rounded-xl bg-black/50 border border-emerald-500/40 text-xs font-bold text-emerald-300 text-center mb-6">
                {t.targetMicroCopy}
              </div>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=pro" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=pro')}`}
              className="w-full py-4 rounded-xl bg-gradient-to-r from-emerald-400 via-emerald-500 to-teal-400 hover:from-emerald-300 hover:to-teal-300 text-[#040407] text-center text-base font-black uppercase tracking-wider shadow-[0_0_35px_rgba(16,185,129,0.6)] transition-all transform hover:scale-[1.03] active:scale-[0.98] animate-pulse block"
            >
              {t.targetCta}
            </Link>
          </div>

          {/* Card 3: The Decoy ($15) -> Third Child = Far Left in RTL */}
          <div className="bg-[#0e1017] rounded-3xl p-6 sm:p-8 border border-white/[0.06] flex flex-col justify-between opacity-80 hover:opacity-100 transition-all">
            <div>
              <div className="text-xs uppercase font-mono text-[#71717a] font-bold mb-2">
                {t.decoyTitle}
              </div>
              <div className="flex items-baseline gap-1 mb-2">
                <span className="text-4xl font-extrabold text-[#a1a1aa]">{t.decoyPrice}</span>
                <span className="text-xs text-[#71717a]">{t.decoyPeriod}</span>
              </div>
              <div className="text-xs font-bold text-rose-400/90 mb-6 bg-rose-500/10 px-3 py-1 rounded-lg inline-block border border-rose-500/20">
                ⚠️ {t.decoyLimit}
              </div>
              <ul className="space-y-3 text-xs text-[#8e8e9c] mb-8 font-medium">
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem1}</li>
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem2}</li>
                <li className="flex items-center gap-2"><span>✕</span> {t.decoyItem3}</li>
              </ul>
            </div>
            <Link
              to={isSignedIn ? "/pricing?plan=starter" : `/sign-up?redirect_url=${encodeURIComponent('/pricing?plan=starter')}`}
              className="w-full py-3.5 rounded-xl border border-white/[0.1] text-center text-xs font-bold text-[#a1a1aa] hover:bg-white/[0.05] transition-colors block"
            >
              {t.decoyCta}
            </Link>
          </div>
        </div>

        {/* Local Payment Trust Badges */}
        <div className="text-center mt-14 space-y-4">
          <div className="text-xs sm:text-sm font-semibold text-[#8e8e9c]">
            {t.paymentTrust}
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3 opacity-75">
            <span className="px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono font-bold text-white">FastPay</span>
            <span className="px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono font-bold text-white">FIB (First Iraqi Bank)</span>
            <span className="px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono font-bold text-white">ZainCash</span>
            <span className="px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono font-bold text-white">AsiaHawala</span>
            <span className="px-3 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono font-bold text-white">Visa / Mastercard</span>
          </div>
        </div>
      </section>

      {/* SECTION 6: THE MANDATORY WEAPONIZED FAQs (Interactive Accordions) */}
      <section id="faq" className="py-24 px-4 sm:px-6 lg:px-10 bg-[#06070a] border-t border-white/[0.08] relative z-10">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16 space-y-3">
            <div className="inline-block px-4 py-1.5 rounded-full text-xs font-black uppercase tracking-widest bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              {t.navFaq}
            </div>
            <h2 className="text-3xl sm:text-5xl font-black text-[#fafafa] tracking-tight">
              {t.faqTitle}
            </h2>
            <p className="text-sm sm:text-base text-[#a1a1aa] font-medium">
              {t.faqSubtitle}
            </p>
          </div>

          <div className="space-y-5">
            {/* FAQ 1 */}
            <div className="bg-[#0e111a] rounded-2xl border border-white/[0.08] overflow-hidden transition-all hover:border-emerald-500/40">
              <button
                onClick={() => setOpenFaq(openFaq === 0 ? null : 0)}
                className="w-full p-6 sm:p-7 text-start flex justify-between items-center gap-4 focus:outline-none"
              >
                <h3 className="text-base sm:text-lg font-black text-[#fafafa] flex items-center gap-3">
                  <span className="text-emerald-400 font-mono">Q1:</span>
                  <span>{t.faq1Q}</span>
                </h3>
                <span className={`w-8 h-8 rounded-full bg-white/[0.05] flex items-center justify-center text-emerald-400 font-bold transition-transform duration-300 ${openFaq === 0 ? "rotate-180 bg-emerald-500/20" : ""}`}>
                  ↓
                </span>
              </button>
              {openFaq === 0 && (
                <div className="px-6 pb-7 sm:px-7 sm:pb-7 text-sm sm:text-base text-[#cfcfd3] leading-relaxed font-medium border-t border-white/[0.06] pt-4">
                  {t.faq1A}
                </div>
              )}
            </div>

            {/* FAQ 2 */}
            <div className="bg-[#0e111a] rounded-2xl border border-white/[0.08] overflow-hidden transition-all hover:border-emerald-500/40">
              <button
                onClick={() => setOpenFaq(openFaq === 1 ? null : 1)}
                className="w-full p-6 sm:p-7 text-start flex justify-between items-center gap-4 focus:outline-none"
              >
                <h3 className="text-base sm:text-lg font-black text-[#fafafa] flex items-center gap-3">
                  <span className="text-emerald-400 font-mono">Q2:</span>
                  <span>{t.faq2Q}</span>
                </h3>
                <span className={`w-8 h-8 rounded-full bg-white/[0.05] flex items-center justify-center text-emerald-400 font-bold transition-transform duration-300 ${openFaq === 1 ? "rotate-180 bg-emerald-500/20" : ""}`}>
                  ↓
                </span>
              </button>
              {openFaq === 1 && (
                <div className="px-6 pb-7 sm:px-7 sm:pb-7 text-sm sm:text-base text-[#cfcfd3] leading-relaxed font-medium border-t border-white/[0.06] pt-4">
                  {t.faq2A}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[#030305] border-t border-white/[0.06] w-full py-16 px-4 sm:px-6 lg:px-10 relative z-10">
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-4 gap-12">
          <div className="col-span-1 md:col-span-2 space-y-4 pr-0 md:pr-8">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 p-0.5 flex items-center justify-center shadow-lg">
                <div className="w-full h-full bg-[#07070a] rounded-[8px] flex items-center justify-center">
                  <span className="text-emerald-400 font-bold text-sm">DB</span>
                </div>
              </div>
              <span className="text-xl font-black text-[#fafafa]">Doblaj</span>
            </div>
            <p className="text-sm text-[#8e8e9c] max-w-sm leading-relaxed font-medium">
              Transforming Kurdish retail videos into Iraqi Arabic tourist magnets with state-of-the-art synthetic voice AI.
            </p>
            <div className="pt-2 text-xs text-[#71717a]">
              <p className="font-bold text-white">{t.footerLegal}</p>
            </div>
            <p className="text-xs text-[#52525b] pt-2">© 2026 FIXDAI LLC d/b/a Doblaj. All rights reserved.</p>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Product Features</h4>
            <ul className="space-y-3 text-sm font-medium">
              <li>
                <a href="#voice-demo" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">{t.navFeatures}</a>
              </li>
              <li>
                <a href="#roi-calculator" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">{t.navCalculator}</a>
              </li>
              <li>
                <a href="#pricing" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">{t.navPricing}</a>
              </li>
              <li>
                <a href="#faq" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">{t.navFaq}</a>
              </li>
            </ul>
          </div>
          <div className="col-span-1 space-y-4">
            <h4 className="text-xs font-bold text-[#fafafa] uppercase tracking-wider">Legal & Security</h4>
            <ul className="space-y-3 text-sm font-medium">
              <li>
                <Link to="/privacy" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">Privacy Policy</Link>
              </li>
              <li>
                <Link to="/terms" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">Terms of Service</Link>
              </li>
              <li>
                <Link to="/refund-policy" className="text-[#8e8e9c] hover:text-emerald-400 transition-colors">Refund Policy</Link>
              </li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  );
}
