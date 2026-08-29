"use client"

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { StorageKeys, setItem } from "@/lib/storage";
import { Card } from "@/components/ui/Card";
import Link from "next/link";

export default function LoginPage() {
    const router = useRouter();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError("");
        setIsSubmitting(true);

        try{
            const { data } = await api.post("/auth/login", { email, password });
            setItem(StorageKeys.accessToken, data.access_token);
            setItem(StorageKeys.refreshToken, data.refresh_token);
            router.push("/");   // redirect to home page after successful login
        } catch (err: any) {
            const message = err?.response?.data?.detail ?? "Login failed.";
            setError(message);
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <Card>
            <h1 className="text-2xl font-bold mb-6">Welcome Back!</h1>

            {error && <div className="alert-error">{error}</div>}

            <form onSubmit={handleSubmit}>
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
                <div className="mb-4">
                    <label htmlFor="password" className="field-label">Password</label>
                    <input
                        id="password"
                        type="password"
                        placeholder="********"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        className="input-field"
                    />
                </div>

                <button type="submit" className="btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? "Logging in..." : "Log In"}
                </button>
            </form>

            <div className="text-sm text-gray-600 mt-4 text-center">
            Don&apos;t have an account? <Link href="/register" className="text-blue-600 underline">Sign up</Link>
            </div>
        </Card>
    );
}