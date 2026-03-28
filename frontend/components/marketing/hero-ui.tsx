"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { BarChart3, LineChart, ShieldCheck } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

export function HeroUI() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center">
      <div className="mx-auto w-full max-w-7xl px-6 py-20">
        <motion.div
          initial="hidden"
          animate="show"
          variants={{
            hidden: {},
            show: { transition: { staggerChildren: 0.08 } },
          }}
          className="max-w-3xl"
        >
          <motion.div
            variants={{
              hidden: { opacity: 0, y: 10, filter: "blur(6px)" },
              show: {
                opacity: 1,
                y: 0,
                filter: "blur(0px)",
                transition: { duration: 0.7, ease: [0.2, 0.8, 0.2, 1] },
              },
            }}
          >
            <Badge
              variant="secondary"
              className="inline-flex items-center gap-2 border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200"
            >
              <ShieldCheck className="h-3.5 w-3.5 text-cyan-300/90" />
              Institutional research, orchestrated end to end
            </Badge>
          </motion.div>

          <motion.h1
            variants={{
              hidden: { opacity: 0, y: 14, filter: "blur(8px)" },
              show: {
                opacity: 1,
                y: 0,
                filter: "blur(0px)",
                transition: { duration: 0.8, ease: [0.2, 0.8, 0.2, 1] },
              },
            }}
            className="mt-6 text-balance text-4xl font-medium tracking-tight text-slate-50 sm:text-5xl lg:text-6xl xl:text-7xl"
          >
            Deep macro and equity research—{" "}
            <span className="bg-gradient-to-r from-cyan-200 via-cyan-400 to-emerald-300 bg-clip-text text-transparent">
              on your timeline
            </span>
            .
          </motion.h1>

          <motion.p
            variants={{
              hidden: { opacity: 0, y: 14 },
              show: {
                opacity: 1,
                y: 0,
                transition: { duration: 0.7, ease: [0.2, 0.8, 0.2, 1] },
              },
            }}
            className="mt-6 max-w-2xl text-pretty text-base leading-relaxed text-slate-200/80 sm:text-lg"
          >
            Ask complex macro and market questions. Your research runs
            asynchronously in the background—pulling trusted data, producing
            interactive charts, and delivering narrative reports where every
            figure traces back to the underlying analysis.
          </motion.p>

          <motion.div
            variants={{
              hidden: { opacity: 0, y: 10 },
              show: {
                opacity: 1,
                y: 0,
                transition: { duration: 0.7, ease: [0.2, 0.8, 0.2, 1] },
              },
            }}
            className="pointer-events-auto mt-10 flex flex-col gap-3 sm:flex-row sm:items-center"
          >
            <Button className="h-11 gap-2 bg-cyan-400/15 text-slate-50 ring-1 ring-cyan-300/25 hover:bg-cyan-400/20">
              <LineChart className="h-4 w-4" />
              Begin research
            </Button>
            <Button
              variant="outline"
              className="h-11 gap-2 border-white/10 bg-white/0 text-slate-100 hover:bg-white/5"
            >
              <BarChart3 className="h-4 w-4" />
              How it works
            </Button>
          </motion.div>

          <motion.div
            variants={{
              hidden: { opacity: 0 },
              show: {
                opacity: 1,
                transition: { delay: 0.2, duration: 0.8 },
              },
            }}
            className="mt-10 flex flex-wrap gap-2 text-xs text-slate-300/70"
          >
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
              Macro & cross-asset coverage
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
              Interactive charts
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
              Source-backed metrics
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1">
              Quality-reviewed reports
            </span>
          </motion.div>
        </motion.div>
      </div>
    </div>
  )
}

