"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearAuthStorage } from "@/lib/storage";

const navItems = [
  { label: "Home", href: "/" },
  { label: "Courses", href: "/courses" },
  { label: "Privacy & Security", href: "/privacy" },
  { label: "Help", href: "/help" }
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  function handleLogout() {
    clearAuthStorage();
    router.push("/login");
  }

  return (
    <aside className="w-56 min-h-screen bg-white border-r p-4 flex flex-col">
      <h2 className="text-lg font-bold mb-6 px-2">SAIV</h2>

      <nav className="flex-1 space-y-1">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`block px-3 py-2 rounded text-sm font-medium ${
              pathname === item.href
                ? "bg-blue-100 text-blue-700"
                : "text-gray-700 hover:bg-gray-100"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <button
        onClick={handleLogout}
        className="px-3 py-2 rounded text-sm font-medium text-red-600 hover:bg-red-50 text-left"
      >
        Logout
      </button>
    </aside>
  );
}