import { headers } from "next/headers";
import { redirect } from "next/navigation";
import ReportLibraryClient from "@/components/report-library-client";
import { auth } from "@/lib/auth";

export default async function ReportsPage() {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/sign-in");
  return <ReportLibraryClient />;
}
