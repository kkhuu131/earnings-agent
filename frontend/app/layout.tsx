import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Earnings Agent",
  description: "Multi-agent earnings call analysis with reputation-weighted predictions",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-screen">
        <nav
          className="fixed top-0 left-0 right-0 z-50 border-b"
          style={{
            background: "var(--color-surface)",
            borderColor: "var(--color-border)",
          }}
        >
          <div className="max-w-7xl mx-auto px-6 h-14 flex items-center gap-8">
            <Link
              href="/"
              className="font-mono font-semibold text-base tracking-tight"
              style={{ color: "var(--color-secondary)" }}
            >
              earnings-agent
            </Link>
            <div className="flex items-center gap-6 text-sm">
              <NavLink href="/">Analyze</NavLink>
              <NavLink href="/history">History</NavLink>
              <NavLink href="/backtest">Backtest</NavLink>
            </div>
          </div>
        </nav>
        <main className="pt-22 max-w-7xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="transition-colors duration-200 hover:text-white cursor-pointer"
      style={{ color: "var(--color-muted)" }}
    >
      {children}
    </Link>
  );
}
