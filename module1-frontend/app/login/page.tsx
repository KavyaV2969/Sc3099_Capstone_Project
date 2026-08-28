"use client"

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { StorageKeys, setItem } from "@/lib/storage";
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
        <div className="login-container">
            <div className="login-card">
                <h1>Welcome Back!</h1>

                {error && <div className="message-error">{error}</div>}

                <form onSubmit={handleSubmit}>
                    <div className="form-field">
                        <label htmlFor="email">Email</label>
                        <input
                            id="email"
                            type="email"
                            placeholder="yourname@e.ntu.edu.sg"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                    </div>
                    <div className="form-field">
                        <label htmlFor="password">Password</label>
                        <input
                            id="password"
                            type="password"
                            placeholder="********"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                        />
                    </div>

                    <button type="submit" className="btn-primary" disabled={isSubmitting}>
                        {isSubmitting ? "Logging in...":"Log In"}
                    </button>
                </form>

                <div className="login-footer">
                    Don&apos;t have an account? <Link href="/register">Sign up</Link>
                </div>
            </div>
        </div>
    );
}