import { redirect } from "next/navigation";
import HomeClient from "@/components/home-client";
import { getServerSession } from "@/lib/server-session";

export default async function Home() {
  const session = await getServerSession();
  if (!session) redirect("/sign-in");
  return <HomeClient />;
}
