import { headers } from "next/headers";
import { redirect } from "next/navigation";
import ChatPageClient from "@/components/chat-page-client";
import { auth } from "@/lib/auth";

export default async function ChatPage({ params }: { params: Promise<{ job_id: string }> }) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/sign-in");
  const { job_id } = await params;
  return <ChatPageClient jobId={job_id} />;
}
