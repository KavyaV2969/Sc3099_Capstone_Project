"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { StorageKeys, setItem } from "@/lib/storage";

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  function isStrongPassword(password: string): boolean {
    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSymbol = /[!@#$%^&*(),.?":{}|<>_\-+=~`[\]/\\;']/.test(password);
    return hasUpper && hasLower && hasNumber && hasSymbol && password.length >= 8;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!email.toLowerCase().endsWith("@e.ntu.edu.sg")) {
      setError("Please use your NTU student email (yourname@e.ntu.edu.sg)")
      return;
    }
    if (!isStrongPassword(password)) {
      setError("Password must contain at least 8 characters and include uppercase, lowercase, symbols and numbers");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      await api.post("/auth/register", {
        email,
        password,
        full_name: fullName,
        // role omitted — backend defaults to "student"
      });
      const { data } = await api.post("/auth/login", { email, password });
      setItem(StorageKeys.accessToken, data.access_token);
      setItem(StorageKeys.refreshToken, data.refresh_token);

      router.push("/consent");
    } catch (err: any) {
      const message = err?.response?.data?.detail ?? "Registration failed.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card>
      <h1 className="text-2xl font-bold mb-6">Create Account</h1>

      {error && <div className="alert-error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="mb-3">
          <label htmlFor="fullName" className="field-label">Full Name</label>
          <input
            id="fullName"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            className="input-field"
          />
        </div>

        <div className="mb-3">
          <label htmlFor="email" className="field-label">Email</label>
          <input
            id="email"
            type="email"
            placeholder="yourname@e.ntu.edu.sg"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="input-field"
          />
        </div>

        <div className="mb-3">
          <label htmlFor="password" className="field-label">Password</label>
          <input
            id="password"
            type="password"
            placeholder="********"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="input-field"
          />
          <p className="text-xs text-gray-500 mt-1">
            Please include uppercase, lowercase, numbers and symbols.
          </p>
        </div>

        <div className="mb-4">
          <label htmlFor="confirmPassword" className="field-label">Confirm Password</label>
          <input
            id="confirmPassword"
            type="password"
            placeholder="********"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            className="input-field"
          />
        </div>

        <button type="submit" className="btn-primary" disabled={isSubmitting}>
          {isSubmitting ? "Creating account..." : "Create Account"}
        </button>
      </form>

      <div className="text-sm text-gray-600 mt-4 text-center">
        Already have an account? <Link href="/login" className="text-blue-600 underline">Log in</Link>
      </div>
    </Card>
  );
}