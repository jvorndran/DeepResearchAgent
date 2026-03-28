"use client"

import { motion } from "framer-motion"
import { MessageSquare, Cpu, FileBarChart } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export function HowItWorks() {
  const steps = [
    {
      badge: "Step 1",
      title: "Clarify",
      description: "Multi-turn chat ensures we understand your parameters before the heavy lifting begins.",
      icon: MessageSquare,
    },
    {
      badge: "Step 2",
      title: "Execute",
      description: "Asynchronous analysis pulls trusted data (FMP, FRED) and runs deterministic computations.",
      icon: Cpu,
    },
    {
      badge: "Step 3",
      title: "Deliver",
      description: "Receive a narrative report with fully interactive, source-backed charts.",
      icon: FileBarChart,
    },
  ]

  const containerVariants = {
    hidden: {},
    show: {
      transition: {
        staggerChildren: 0.2,
      },
    },
  }

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    show: { 
      opacity: 1, 
      y: 0,
      transition: {
        type: "spring",
        stiffness: 100,
        damping: 15,
      }
    },
  }

  return (
    <section id="how-it-works" className="py-24 bg-black">
      <div className="container mx-auto max-w-7xl px-6">
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.7 }}
          className="text-center mb-16"
        >
          <h2 className="text-3xl font-medium tracking-tight text-slate-50 sm:text-4xl">
            How it works
          </h2>
          <p className="mt-4 text-lg text-slate-400 max-w-2xl mx-auto">
            A transparent, observable pipeline that separates narrative synthesis from raw-number work.
          </p>
        </motion.div>

        <motion.div 
          variants={containerVariants}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-100px" }}
          className="grid grid-cols-1 md:grid-cols-3 gap-8 relative"
        >
          {/* Connecting line for desktop */}
          <div className="hidden md:block absolute top-1/2 left-[10%] right-[10%] h-[1px] bg-white/10 -translate-y-1/2 z-0 overflow-hidden">
            <motion.div 
              initial={{ x: "-100%" }}
              animate={{ x: "100%" }}
              transition={{ 
                repeat: Infinity, 
                duration: 2.5, 
                ease: "linear",
                repeatDelay: 0.5
              }}
              className="w-1/3 h-full bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-50"
            />
          </div>

          {steps.map((step, index) => (
            <motion.div key={index} variants={itemVariants} className="relative z-10">
              {/* Pulsing glow behind the card */}
              <motion.div
                animate={{
                  opacity: [0.1, 0.3, 0.1],
                  scale: [1, 1.02, 1],
                }}
                transition={{
                  duration: 3,
                  repeat: Infinity,
                  delay: index * 0.8, // Stagger the pulse based on card order
                  ease: "easeInOut",
                }}
                className="absolute -inset-1 rounded-xl bg-cyan-400/20 blur-xl z-0"
              />
              <Card className="relative z-10 bg-black/40 border-white/10 backdrop-blur-sm h-full hover:border-white/20 transition-colors duration-300">
                <CardHeader>
                  <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-cyan-400/10 ring-1 ring-cyan-400/20">
                    <step.icon className="h-6 w-6 text-cyan-400" />
                  </div>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="secondary" className="bg-white/5 text-slate-300 hover:bg-white/10 border-white/10">
                      {step.badge}
                    </Badge>
                  </div>
                  <CardTitle className="text-xl text-slate-50">{step.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-base text-slate-400">
                    {step.description}
                  </CardDescription>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
