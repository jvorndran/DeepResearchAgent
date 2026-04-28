import { redirect } from "next/navigation";
import ReportLibraryClient from "@/components/report-library-client";
import { getServerSession } from "@/lib/server-session";

export default async function ReportsPage() {
  const session = await getServerSession();
  if (!session) redirect("/sign-in");
  return <ReportLibraryClient />;
}
