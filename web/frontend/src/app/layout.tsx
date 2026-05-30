import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'GhostWriter',
  description: 'Turn standups into shipped code',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
