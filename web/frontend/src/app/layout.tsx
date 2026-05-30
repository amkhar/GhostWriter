import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'GhostWriter',
  description: 'Turn standups into shipped code',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
