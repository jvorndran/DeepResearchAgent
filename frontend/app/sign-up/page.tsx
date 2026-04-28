import { redirect } from "next/navigation";
import AuthForm from "@/components/auth-form";
import { getServerSession } from "@/lib/server-session";

export default async function SignUpPage() {
  const session = await getServerSession();
  if (session) redirect("/");
  return <AuthForm mode="sign-up" />;
}
