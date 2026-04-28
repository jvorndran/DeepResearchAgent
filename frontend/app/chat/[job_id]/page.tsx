import { redirect } from "next/navigation";
import ChatPageClient from "@/components/chat-page-client";
import { getServerSession } from "@/lib/server-session";

export default async function ChatPage({ params }: { params: Promise<{ job_id: string }> }) {
  const session = await getServerSession();
  if (!session) redirect("/sign-in");
  const { job_id } = await params;
  return <ChatPageClient jobId={job_id} />;
}
