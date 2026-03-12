import React from 'react';
import { ChevronDown } from 'lucide-react';

export interface AccordionItem {
  id: string;
  title: string;
  content: React.ReactNode;
  disabled?: boolean;
}

export interface AccordionProps {
  /**
   * Array of accordion items
   */
  items: AccordionItem[];
  
  /**
   * Allow multiple items to be open
   * @default false
   */
  multiple?: boolean;
  
  /**
   * Default open item IDs
   */
  defaultOpen?: string[];
}

/**
 * Accordion Component
 * 
 * Accessible accordion/collapse component with keyboard navigation.
 * Meets WCAG 2.1 AA standards with proper ARIA attributes.
 * 
 * @example
 * ```tsx
 * <Accordion
 *   items={[
 *     { id: '1', title: 'Section 1', content: <p>Content 1</p> },
 *     { id: '2', title: 'Section 2', content: <p>Content 2</p> }
 *   ]}
 * />
 * ```
 */
export const Accordion: React.FC<AccordionProps> = ({
  items,
  multiple = false,
  defaultOpen = [],
}) => {
  const [openItems, setOpenItems] = React.useState<string[]>(defaultOpen);
  
  const toggleItem = (id: string) => {
    setOpenItems((prev) => {
      if (prev.includes(id)) {
        return prev.filter((itemId) => itemId !== id);
      }
      
      if (multiple) {
        return [...prev, id];
      }
      
      return [id];
    });
  };
  
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const isOpen = openItems.includes(item.id);
        
        return (
          <div
            key={item.id}
            className="border border-slate-200 rounded-lg overflow-hidden"
          >
            <button
              onClick={() => !item.disabled && toggleItem(item.id)}
              disabled={item.disabled}
              aria-expanded={isOpen}
              aria-controls={`content-${item.id}`}
              id={`header-${item.id}`}
              className="w-full flex items-center justify-between px-4 py-3 text-left font-medium text-slate-900 bg-white hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset"
            >
              <span>{item.title}</span>
              <ChevronDown
                className={`w-5 h-5 text-slate-500 transition-transform ${
                  isOpen ? 'rotate-180' : ''
                }`}
                aria-hidden="true"
              />
            </button>
            
            <div
              id={`content-${item.id}`}
              role="region"
              aria-labelledby={`header-${item.id}`}
              hidden={!isOpen}
              className={`px-4 py-3 bg-slate-50 border-t border-slate-200 ${
                isOpen ? 'block' : 'hidden'
              }`}
            >
              {item.content}
            </div>
          </div>
        );
      })}
    </div>
  );
};
