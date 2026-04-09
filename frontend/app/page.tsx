"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useResearchStream } from "@/hooks/use-research-stream";
import AppHeader from "@/components/app-header";
import ChatInterface from "@/components/chat-interface";
import type { Message } from "@/lib/types";

export default function Home() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [submittedMessages, setSubmittedMessages] = useState<Message[]>([]);
  const [pendingApprovalJobId, setPendingApprovalJobId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  /** Same id as backend LangGraph thread — set from first SSE `start` so resume/Commence hits the same checkpoint. */
  const [sessionJobId, setSessionJobId] = useState("");

  const { isStreamingChat, orchestratorText } = useResearchStream({
    jobId: sessionJobId,
    messages: submittedMessages,
    streamTelemetry: false,
    onJobId: setSessionJobId,
    onApprovalRequired: (id) => {
      setPendingApprovalJobId(id);
    },
    onResearchExecutionStarted: () => {
      setPendingApprovalJobId(null);
    },
    onConversationalFinish: (text) => {
      setMessages((prev) => [...prev, { role: "assistant", content: text }]);
    },
  });

  const handleSend = (forceResearch = false) => {
    if (!forceResearch && !inputValue.trim()) return;
    if (forceResearch && pendingApprovalJobId) {
      // Save resume payload for the chat page, then navigate immediately.
      // The chat page opens the SSE connection so research streams there.
      const resume = { decisions: [{ type: "approve" as const }] };
      sessionStorage.setItem("pending_resume", JSON.stringify(resume));
      router.push(`/chat/${sessionJobId}`);
      return;
    }
    const userMsg = forceResearch
      ? "Please begin the research now with the parameters discussed."
      : inputValue.trim();
    const newMessages: Message[] = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);
    setSubmittedMessages(newMessages);
    if (!forceResearch) setInputValue("");
  };

  return (
    <div className="flex min-h-0 h-screen flex-col bg-background">
      <AppHeader />
      <main className="flex min-h-0 flex-1 flex-col">
        <ChatInterface
          messages={messages}
          isStreamingChat={isStreamingChat}
          orchestratorText={orchestratorText}
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSend={() => handleSend(false)}
          onBeginResearch={() => handleSend(true)}
        />
      </main>
    </div>
  );
}
