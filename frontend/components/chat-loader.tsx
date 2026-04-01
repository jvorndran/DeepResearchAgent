import { Sparkles } from "lucide-react"

export function ChatLoader() {
  return (
    <div className="group flex gap-3 flex-row animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-transform duration-200 group-hover:scale-105 bg-gradient-to-br from-accent/20 to-accent/5 ring-1 ring-accent/30">
        <Sparkles className="h-4 w-4 text-accent" />
        <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-sidebar bg-emerald-500" />
      </div>

      <div className="flex max-w-[min(100%,36rem)] flex-col gap-1 items-start">
        <div className="relative flex h-[38px] items-center gap-1.5 overflow-hidden rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed transition-all duration-200 bg-gradient-to-br from-secondary/90 to-secondary/70 text-secondary-foreground rounded-bl-md ring-1 ring-border/30 backdrop-blur-sm">
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/3 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
          <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
          <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
          <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
        </div>
      </div>
    </div>
  )
}
