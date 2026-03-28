"use client"

import { LineChart } from "lucide-react"
import { Button } from "@/components/ui/button"

export function FinalCTA() {
  return (
    <section className="py-24 bg-black border-t border-white/5">
      <div className="container mx-auto max-w-4xl px-6 text-center">
        <h2 className="text-3xl font-medium tracking-tight text-slate-50 sm:text-5xl">
          Stop waiting at a chat window.
        </h2>
        <p className="mt-6 text-lg text-slate-400 max-w-2xl mx-auto">
          Start your deep research run today. Get source-backed, institutional-grade analysis delivered asynchronously.
        </p>
        <div className="mt-10 flex justify-center">
          <Button size="lg" className="h-12 px-8 gap-2 bg-cyan-400/15 text-slate-50 ring-1 ring-cyan-300/25 hover:bg-cyan-400/20 text-base">
            <LineChart className="h-5 w-5" />
            Begin your first research run
          </Button>
        </div>
      </div>
    </section>
  )
}
