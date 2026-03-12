import React from 'react';
import { ChevronRight } from 'lucide-react';

export interface BreadcrumbItem {
  label: string;
  href?: string;
  onClick?: () => void;
}

export interface BreadcrumbProps {
  /**
   * Breadcrumb items
   */
  items: BreadcrumbItem[];
  
  /**
   * Custom separator
   */
  separator?: React.ReactNode;
}

/**
 * Breadcrumb Component
 * 
 * Accessible navigation breadcrumbs showing current location.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * 
 * @example
 * ```tsx
 * <Breadcrumb
 *   items={[
 *     { label: 'Home', href: '/' },
 *     { label: 'Cases', href: '/cases' },
 *     { label: 'Case #12345' }
 *   ]}
 * />
 * ```
 */
export const Breadcrumb: React.FC<BreadcrumbProps> = ({
  items,
  separator = <ChevronRight className="w-4 h-4" />,
}) => {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex items-center gap-2 text-sm">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          
          return (
            <li key={index} className="flex items-center gap-2">
              {item.href ? (
                <a
                  href={item.href}
                  onClick={item.onClick}
                  className="text-blue-600 hover:text-blue-700 hover:underline transition-colors"
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </a>
              ) : (
                <span
                  className={isLast ? 'text-slate-900 font-medium' : 'text-slate-600'}
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              )}
              
              {!isLast && (
                <span className="text-slate-400" aria-hidden="true">
                  {separator}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};
