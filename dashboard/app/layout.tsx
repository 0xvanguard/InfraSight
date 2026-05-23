import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "InfraSight",
  description:
    "Monitorización remota e inteligencia de endpoints para entornos empresariales distribuidos.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <body className="min-h-screen">
        <header className="border-b border-border bg-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/" className="text-xl font-semibold text-foreground">
              InfraSight
            </Link>
            <nav className="flex gap-6 text-sm text-muted">
              <Link href="/" className="hover:text-foreground">
                Parque
              </Link>
              <span className="opacity-60">Alertas (M3)</span>
              <span className="opacity-60">Intervenciones (M3)</span>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 py-8 text-xs text-muted">
          InfraSight - Walking skeleton (M1)
        </footer>
      </body>
    </html>
  );
}
