'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const TABS = [
  { href: '/', label: 'Analyse' },
  { href: '/journal', label: 'Journal' },
];

export function Nav() {
  const path = usePathname();
  return (
    <header className="topbar">
      <span className="dot" />
      <h1>Gold Desk</h1>
      <nav className="tabs">
        {TABS.map((t) => (
          <Link key={t.href} href={t.href} className="tab" data-active={path === t.href}>
            {t.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
