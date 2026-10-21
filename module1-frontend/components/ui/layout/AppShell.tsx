"use client";
import { useState } from "react";
import { Sidebar } from "./Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);

    return (
        <div className="flex">
        <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />

        <div className="flex-1">
            <button
            onClick={() => setIsSidebarOpen(true)}
            className="m-4 p-2 rounded hover:bg-gray-100"
            aria-label="Open menu"
            >
            {/* simple hamburger icon, no icon library needed */}
            <div className="w-6 h-0.5 bg-gray-700 mb-1"></div>
            <div className="w-6 h-0.5 bg-gray-700 mb-1"></div>
            <div className="w-6 h-0.5 bg-gray-700"></div>
            </button>

            <div className="p-8 pt-0">{children}</div>
        </div>
        </div>
    );
}