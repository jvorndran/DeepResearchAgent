AI Development Rules: shadcn/ui & Tailwind Consistency
Core Directives
You are a frontend expert. You must strictly adhere to the following styling and architectural rules. Consistency with the existing design system is non-negotiable.

1. Component Usage
• Source of Truth: Only use components located in `@/components/ui`.
• No Raw HTML: Never use `<button>`, `<input>`, or `<table>`. Use the corresponding shadcn component (e.g., `<Button>`, `<Input>`, `<DataTable>`).
• Imports: Always use the `@/` alias for local imports.

2. Theming & Colors (High-End Editorial / Brutalist-Luxury)
• Design Tokens: Strictly use Tailwind utility classes that reference the CSS variables defined in `globals.css`.
• Colors: Use semantic tokens only (`bg-background`, `text-foreground`, `bg-primary`, `text-muted-foreground`, `border-border`).
• No Hardcoding: Never use arbitrary hex codes or generic Tailwind colors. The entire app uses `oklch` semantic CSS variables.

3. Typography System (3-Tier)
• Headings / Display (`font-serif`): Uses Cormorant Garamond. Use for massive, impactful titles. Always pair with tight tracking (e.g., `font-serif text-5xl tracking-tight`).
• Body / Micro-copy (`font-sans`): Uses Manrope. Use for readable paragraphs (`font-light leading-relaxed`) and highly stylized uppercase labels (`text-[10px] uppercase tracking-[0.2em]`).
• Data / Telemetry (`font-mono`): Uses the system monospace font. Use for logs, code blocks, and technical data.

4. Layout, Spacing & Shape
• Shape: The brutalist aesthetic relies on sharp, 90-degree corners. `--radius` is globally set to `0px`. Do NOT use `rounded-md`, `rounded-lg`, or `rounded-full` unless absolutely necessary for a specific micro-interaction (like a pulsing dot).
• Use the standard Tailwind spacing scale (e.g., `p-4`, `m-2`, `gap-6`).
• For containers, use the `max-w-x` classes or the `Container` component if available.

5. Motion & Animations
• Page Loads & Mounts: Use Tailwind's `tailwindcss-animate` plugin classes to create slow, cinematic fade-up effects (e.g., `animate-in fade-in slide-in-from-bottom-8 duration-1000`).
• Hover States: Rely on CSS transitions. Use `transition-all duration-500` along with `group` and `group-hover:` to create slow, deliberate hover effects (like subtle background glows).

6. Implementation Checklist
• Ensure `dark:` mode compatibility by using the semantic color classes listed above.
• If a shadcn component is missing, inform the user to install it via `npx shadcn-ui@latest add [component]`.