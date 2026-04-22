"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useResearchStream } from "@/hooks/use-research-stream";
import AppHeader from "@/components/app-header";
import ChatInterface from "@/components/chat-interface";
import type { Message } from "@/lib/types";

const APPROVAL_MESSAGE_CONTENT = "Please begin the research now with the parameters discussed.";

function buildApprovalMessage(): Message {
  return {
    role: "user",
    content: APPROVAL_MESSAGE_CONTENT,
    metadata: { action: "commence_research" },
  } as unknown as Message;
}

export default function Home() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [submittedMessages, setSubmittedMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  /** Same id as backend LangGraph thread — set from first SSE `start` so Commence navigates to the same checkpoint. */
  const [sessionJobId, setSessionJobId] = useState("");

  const { isStreamingChat, orchestratorText } = useResearchStream({
    jobId: sessionJobId,
    messages: submittedMessages,
    streamTelemetry: false,
    onJobId: setSessionJobId,
    onConversationalFinish: (text) => {
      setMessages((prev) => [...prev, { role: "assistant", content: text }]);
    },
  });

  const handleSend = (forceResearch = false) => {
    if (!forceResearch && !inputValue.trim()) return;
    if (forceResearch && sessionJobId) {
      // Always navigate to the chat page with the approval action.
      // The chat page sends this message to the same LangGraph thread.
      // - If the graph is interrupted at approval_gate → resumes the interrupt.
      // - If not interrupted → backend sets phase="executing" (manual override).
      const approvalMessage = buildApprovalMessage();
      sessionStorage.setItem(
        "pending_messages",
        JSON.stringify([approvalMessage])
      );
      router.push(`/chat/${sessionJobId}`);
      return;
    }
    const newMessages: Message[] = [
      ...messages,
      { role: "user", content: inputValue.trim() },
    ];
    setMessages(newMessages);
    setSubmittedMessages(newMessages);
    setInputValue("");
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