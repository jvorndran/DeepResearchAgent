"use client"

import { HeroUI } from "@/components/marketing/hero-ui"
import { MacroDataNexus } from "@/components/marketing/macro-data-nexus"
import { HowItWorks } from "@/components/marketing/how-it-works"
import { FinalCTA } from "@/components/marketing/final-cta"

export default function Page() {
  return (
    <div className="flex-1 w-full flex flex-col min-h-screen bg-black text-slate-50">
      <main className="flex-1 w-full flex flex-col">
        <section className="relative h-svh w-full overflow-hidden">
          <MacroDataNexus />
          <HeroUI />
        </section>
        <HowItWorks />
        <FinalCTA />
      </main>
    </div>
  )
}
