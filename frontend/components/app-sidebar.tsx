"use client"

import { FileText, Plus } from "lucide-react"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"

export interface ReportHistoryItem {
  id: string
  title: string
  createdAt: string
}

interface AppSidebarProps {
  reports: ReportHistoryItem[]
  activeReportId?: string | null
  onNewResearch: () => void
  onSelectReport: (id: string) => void
}

export function AppSidebar({
  reports,
  activeReportId,
  onNewResearch,
  onSelectReport,
}: AppSidebarProps) {
  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="border-b border-sidebar-border p-2">
        <Button
          className="w-full justify-start gap-2"
          size="sm"
          onClick={onNewResearch}
        >
          <Plus className="size-4 shrink-0" />
          <span className="group-data-[collapsible=icon]:hidden">New Research</span>
        </Button>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Previous reports</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {reports.length === 0 ? (
                <p className="px-2 py-3 text-xs text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden">
                  No reports yet. Start a research session to see it here.
                </p>
              ) : (
                reports.map((report) => (
                  <SidebarMenuItem key={report.id}>
                    <SidebarMenuButton
                      isActive={activeReportId === report.id}
                      tooltip={report.title}
                      onClick={() => onSelectReport(report.id)}
                    >
                      <FileText className="size-4 shrink-0" />
                      <span className="truncate">{report.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
