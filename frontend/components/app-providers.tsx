"use client"

import { SidebarProvider } from "@/components/ui/sidebar"

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider defaultOpen={false}>{children}</SidebarProvider>
  )
}
