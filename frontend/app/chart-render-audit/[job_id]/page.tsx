import { notFound } from "next/navigation";
import ChatPageClient from "@/components/chat-page-client";

export default async function ChartRenderAuditPage({
  params,
}: {
  params: Promise<{ job_id: string }>;
}) {
  if (process.env.NODE_ENV === "production") notFound();
  const { job_id } = await params;
  return <ChatPageClient jobId={job_id} />;
}
