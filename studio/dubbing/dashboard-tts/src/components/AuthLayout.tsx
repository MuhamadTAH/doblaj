import React from "react";

interface AuthLayoutProps {
  children: React.ReactNode;
  title: string;
  subtitle: string;
}

export default function AuthLayout({ children, title, subtitle }: AuthLayoutProps) {
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      {/* Container */}
      <main className="w-full max-w-6xl flex flex-col md:flex-row studio-card rounded-2xl overflow-hidden min-h-[680px]">
        {/* Left Pane - Login Form */}
        <section className="flex-1 p-8 md:p-16 flex flex-col justify-center relative">
          <header className="mb-10 text-center md:text-left">
            <div className="mb-8 flex justify-center md:justify-start">
              <svg fill="none" height="40" viewBox="0 0 40 40" width="40" xmlns="http://www.w3.org/2000/svg">
                <rect fill="#38bdf8" height="40" rx="8" width="40"></rect>
                <path d="M12 12H18L28 28H22L12 12Z" fill="white"></path>
                <circle cx="15" cy="28" fill="white" r="3"></circle>
              </svg>
            </div>
            <h1 className="text-4xl font-bold text-white mb-2">{title}</h1>
            <p className="text-ink-200">{subtitle}</p>
          </header>
          
          <div className="w-full max-w-md mx-auto md:mx-0">
            {children}
          </div>
        </section>

        {/* Right Pane - Testimonial/Branding */}
        <section className="relative flex-1 bg-ink-900 p-12 md:p-16 flex flex-col justify-between overflow-hidden hidden md:flex">
          {/* Decorative geometric element */}
          <div className="absolute -right-20 top-1/2 -translate-y-1/2 w-[400px] h-[400px] geometric-star"></div>
          
          <div className="relative z-10 max-w-md mt-auto mb-auto">
            <h2 className="text-4xl font-bold leading-tight mb-8 text-white">What’s our Jobseekers Said.</h2>
            <div className="space-y-6">
              <svg className="w-10 h-10 text-brand-400 opacity-40" fill="currentColor" viewBox="0 0 24 24">
                <path d="M14.017 21L14.017 18C14.017 16.8954 14.9124 16 16.017 16H19.017C19.5693 16 20.017 15.5523 20.017 15V9C20.017 8.44772 19.5693 8 19.017 8H15.017C14.4647 8 14.017 8.44772 14.017 9V12C14.017 12.5523 13.5693 13 13.017 13H11.017C10.4647 13 10.017 12.5523 10.017 12V6C10.017 4.89543 10.9124 4 12.017 4H19.017C21.2261 4 23.017 5.79086 23.017 8V15C23.017 18.3137 20.3307 21 17.017 21H14.017ZM3.017 21L3.017 18C3.017 16.8954 3.91243 16 5.017 16H8.017C8.56928 16 9.017 15.5523 9.017 15V9C9.017 8.44772 8.56928 8 8.017 8H4.017C3.46472 8 3.017 8.44772 3.017 9V12C3.017 12.5523 2.56928 13 2.017 13H0.017C-0.53528 13 -1.017 12.5523 -1.017 12V6C-1.017 4.89543 -0.12157 4 0.983 4H8.017C10.2261 4 12.017 5.79086 12.017 8V15C12.017 18.3137 9.33072 21 6.017 21H3.017Z"></path>
              </svg>
              <p className="text-xl text-white italic leading-relaxed">
                "Search and find your dream job is now easier than ever. Just browse a job and apply if you need to."
              </p>
              <div>
                <p className="font-bold text-white">Mas Parjono</p>
                <p className="text-ink-200 text-sm">UI Designer at Google</p>
              </div>
            </div>
          </div>

          {/* Overlapping Floating Card */}
          <div className="relative z-20 mt-12 md:mt-0 md:absolute md:-bottom-4 md:-right-4 w-full md:max-w-xs p-6 glass-pane rounded-xl shadow-2xl">
            <h3 className="font-bold text-lg mb-2 text-white">Get your right job and right place apply now</h3>
            <p className="text-ink-200 text-sm mb-4">Be among the first founders to experience the easiest way to start run a business.</p>
            <div className="flex items-center space-x-2">
              <div className="flex -space-x-2 overflow-hidden">
                <img alt="" className="inline-block h-8 w-8 rounded-full ring-2 ring-ink-900" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBI-te0xmBDKh-XaiGrKLnDXL-SXvbVU6am-3piJo21zg8Hh7Teg5kBRhqaL1uj23lU53AmIHEzyV1omUVYn21yhVuTVWQiiFMkNrIV5ccQoyAcHW2Bqq_Oz14wQaE1J7DvQ_CsXzIQCGV9kjuZ9OWc6gCm6ZjqTp4a0qOLEueujY4L_sgHfotfr4Ictons352wwjt_GSuNbAdPSIXXJWPEO_nyRJGtzcbXb_Ao17EtlUWGvY-u3a4RFg"/>
                <img alt="" className="inline-block h-8 w-8 rounded-full ring-2 ring-ink-900" src="https://lh3.googleusercontent.com/aida-public/AB6AXuD52IxMBHnq1gPyItFzqG4xJhDg5UNwSlXDOCBNP7jC2yDtkJb-uAECBY1JFQplZ-nR53HrS4XijNsUGAepxNOxc6EdjG05w1-MLDCKBJeRzdxSY5cDEGx76Il2P8NP6eEty6dCHsk4WRjYBkP_WRuDgYwRauu-XySoSG1ZRxnmoTDRZYlnJ58OptRUK7s-pSMfiw-JEWwTQUkRCY2wrL6ZFKHmEjh3rOlY8kEgoLaaOtLY9ABMGS29Ig"/>
                <img alt="" className="inline-block h-8 w-8 rounded-full ring-2 ring-ink-900" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAWAtxjneO-CN5NjuY8u9s6dXTcg8VO4kLeTwGlNqR7bO7om--gtfimvM8tPYNpXfB2Tnigi7u0Fp6k6_U54YYzYn9XPaCPZjPjbBKxkV_XjtmxQN-YCMsvg90f2_-Li-_-Pz-0PFBzmJgzTt_Kp9E9cpWGDpOgYUwSHRamF8PlHefJiesGY5vxoYX-pwCOBQpbFt8RwK-WLYnRQ_dy69KJK7U8cMpMfuIZNYsoe2w5rvG99XaKLLFSLg"/>
                <div className="inline-block h-8 w-8 rounded-full ring-2 ring-ink-900 bg-ink-600 flex items-center justify-center text-[10px] font-medium text-white">+1k</div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
