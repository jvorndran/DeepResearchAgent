"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight } from "@phosphor-icons/react";
import { authClient } from "@/lib/auth-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function AuthForm({ mode }: { mode: "sign-in" | "sign-up" }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const isSignUp = mode === "sign-up";

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setPending(true);
    const result = isSignUp
      ? await authClient.signUp.email({ name, email, password })
      : await authClient.signIn.email({ email, password });
    setPending(false);
    if (result.error) {
      setError(result.error.message ?? "Authentication failed");
      return;
    }
    router.push("/");
    router.refresh();
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <div className="w-full max-w-md border border-border bg-card px-8 py-10 shadow-xl">
        <div className="mb-10">
          <div className="w-12 h-12 border border-primary flex items-center justify-center text-primary mb-6">
            <span className="font-serif text-2xl italic">D</span>
          </div>
          <h1 className="text-4xl font-serif tracking-tight mb-3">
            {isSignUp ? "Create account" : "Sign in"}
          </h1>
          <p className="text-sm text-muted-foreground font-sans leading-relaxed">
            Authenticated research keeps jobs and saved reports scoped to your account.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5" data-testid="auth-form">
          {isSignUp && (
            <label className="flex flex-col gap-2">
              <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans">
                Name
              </span>
              <Input
                data-testid="auth-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
          )}
          <label className="flex flex-col gap-2">
            <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans">
              Email
            </span>
            <Input
              data-testid="auth-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans">
              Password
            </span>
            <Input
              data-testid="auth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </label>

          {error && <p className="text-sm text-destructive font-sans" data-testid="auth-error">{error}</p>}

          <Button
            type="submit"
            data-testid="auth-submit"
            disabled={pending}
            className="mt-2 rounded-none bg-foreground text-background hover:bg-primary hover:text-primary-foreground uppercase tracking-[0.16em] text-xs h-11"
          >
            {pending ? "Working..." : isSignUp ? "Sign Up" : "Sign In"}
            <ArrowRight size={16} />
          </Button>
        </form>

        <div className="mt-8 text-sm text-muted-foreground font-sans">
          {isSignUp ? "Already have an account? " : "Need an account? "}
          <Link href={isSignUp ? "/sign-in" : "/sign-up"} className="text-primary hover:underline">
            {isSignUp ? "Sign in" : "Sign up"}
          </Link>
        </div>
      </div>
    </div>
  );
}
