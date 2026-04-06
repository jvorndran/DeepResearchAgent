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
  const [inputValue, setInputValue] = useState("");

  const { isStreamingChat, orchestratorText } = useResearchStream({
    jobId: "",
    messages: submittedMessages,
    onNavigate: (id) => {
      sessionStorage.setItem("pending_messages", JSON.stringify(submittedMessages));
      router.push(`/chat/${id}`);
    },
    onConversationalFinish: (text) => {
      setMessages((prev) => [...prev, { role: "assistant", content: text }]);
    },
  });

  const handleSend = (forceResearch = false) => {
    if (!forceResearch && !inputValue.trim()) return;
    const userMsg = forceResearch
      ? "Please begin the research now with the parameters discussed."
      : inputValue.trim();
    const newMessages: Message[] = [...messages, { role: "user", content: userMsg }];
    setMessages(newMessages);
    setSubmittedMessages(newMessages);
    if (!forceResearch) setInputValue("");
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      <AppHeader />
      <main className="flex-1 overflow-hidden flex flex-col">
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
